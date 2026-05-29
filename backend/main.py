import os
import sys
import json
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from backend.config import get_settings
from backend.scrapers import playstore, appstore
from backend.integrations.revenuecat import RevenueCatClient
from backend.integrations.stripe_client import StripeClient
from backend.integrations.click_uzum import ClickClient, UzumClient
from backend.security.scanner import scan_target
from backend.ai.analyzer import analyze_reviews
from backend.ai.aso import score_aso
from backend.ai.privacy import analyze_privacy_policy
from backend.ai.osint import full_domain_osint

connected_providers: dict[str, dict] = {}
scan_cache: dict[str, dict] = {}  # bounded to 50 entries


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.revenuecat_api_key:
        connected_providers["revenuecat"] = {"api_key": settings.revenuecat_api_key, "project_id": settings.revenuecat_project_id}
    if settings.stripe_secret_key:
        connected_providers["stripe"] = {"api_key": settings.stripe_secret_key}
    if settings.click_merchant_id:
        connected_providers["click"] = {"merchant_id": settings.click_merchant_id, "service_id": settings.click_service_id, "secret_key": settings.click_secret_key}
    if settings.uzum_merchant_id:
        connected_providers["uzum"] = {"merchant_id": settings.uzum_merchant_id, "api_key": settings.uzum_api_key}
    yield


app = FastAPI(title="AppInsight", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/")
async def serve_frontend():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


# ─── Store ──────────────────────────────────────────────────────

@app.get("/api/store/search")
async def search_store(q: str, store: str = "playstore", count: int = Query(default=20, le=50), country: str = "all"):
    if store == "playstore":
        return await playstore.search_apps(q, count=count, country=country)
    elif store == "appstore":
        return await appstore.search_apps(q, count=count, country=country)
    raise HTTPException(400, "Invalid store.")


@app.get("/api/store/app/{store}/{app_id:path}")
async def get_app_info(store: str, app_id: str, country: str = "all"):
    if store not in ("playstore", "appstore"):
        raise HTTPException(400, "Invalid store.")
    try:
        if store == "playstore":
            return await playstore.get_app_info(app_id, country=country)
        else:
            return await appstore.get_app_info(app_id, country=country)
    except Exception as e:
        raise HTTPException(404, f"App not found: {e}")


@app.get("/api/store/reviews/{store}/{app_id:path}")
async def get_reviews(store: str, app_id: str, count: int = Query(default=200, le=1000), country: str = "all", sort: str = "newest"):
    if store not in ("playstore", "appstore"):
        raise HTTPException(400, "Invalid store.")
    try:
        if store == "playstore":
            return await playstore.get_reviews(app_id, count=count, country=country, sort=sort)
        else:
            return await appstore.get_reviews(app_id, count=count, country=country)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch reviews: {e}")


@app.get("/api/store/similar/{store}/{app_id:path}")
async def get_similar_apps(store: str, app_id: str, country: str = "all"):
    if store == "playstore":
        return await playstore.get_similar_apps(app_id, country=country)
    elif store == "appstore":
        return await appstore.search_apps(app_id, count=10, country=country)
    raise HTTPException(400, "Invalid store.")


@app.get("/api/store/developer-domain/{app_id:path}")
async def get_developer_domain(app_id: str, country: str = "all"):
    """Get developer website and privacy policy URL without AI analysis."""
    from google_play_scraper import app as gp_app
    c = country if country != "all" else "us"
    try:
        raw = await asyncio.get_running_loop().run_in_executor(None, lambda: gp_app(app_id, country=c))
        return {
            "developer_website": raw.get("developerWebsite"),
            "developer_email": raw.get("developerEmail"),
            "privacy_policy": raw.get("privacyPolicy"),
        }
    except Exception:
        return {"developer_website": None, "developer_email": None, "privacy_policy": None}


@app.get("/api/store/permissions/{app_id:path}")
async def get_permissions(app_id: str, country: str = "all"):
    try:
        return await playstore.get_permissions(app_id, country=country)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch permissions: {e}")


@app.get("/api/store/privacy/{store}/{app_id:path}")
async def get_privacy_analysis(store: str, app_id: str, country: str = "all"):
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(400, "GEMINI_API_KEY not configured.")
    try:
        if store == "playstore":
            info = await playstore.get_app_info(app_id, country=country)
        else:
            info = await appstore.get_app_info(app_id, country=country)
    except Exception:
        raise HTTPException(404, "App not found")

    # Get privacy policy URL from app data
    # Play Store returns it in the raw data, but our model doesn't have it.
    # Fetch raw data to get the URL.
    if store == "playstore":
        from google_play_scraper import app as gp_app
        raw = await asyncio.get_running_loop().run_in_executor(
            None, lambda: gp_app(app_id, country=country if country != "all" else "us")
        )
        policy_url = raw.get("privacyPolicy")
    else:
        policy_url = None

    if not policy_url:
        raise HTTPException(404, "No privacy policy URL found for this app.")

    try:
        result = await analyze_privacy_policy(policy_url, info.title, settings.gemini_api_key)
        return result
    except Exception as e:
        raise HTTPException(500, f"Privacy analysis failed: {e}")


@app.get("/api/osint/{domain:path}")
async def osint_lookup(domain: str):
    try:
        return await full_domain_osint(domain)
    except Exception as e:
        raise HTTPException(500, f"OSINT lookup failed: {e}")


@app.get("/api/store/aso/{store}/{app_id:path}")
async def get_aso_score(store: str, app_id: str, country: str = "all"):
    if store not in ("playstore", "appstore"):
        raise HTTPException(400, "Invalid store.")
    try:
        if store == "playstore":
            info = await playstore.get_app_info(app_id, country=country)
        else:
            info = await appstore.get_app_info(app_id, country=country)
        return score_aso(info)
    except Exception as e:
        raise HTTPException(500, f"ASO scoring failed: {e}")


class CompareRequest(BaseModel):
    apps: list[dict]  # [{app_id, store, country}]

@app.post("/api/store/compare")
async def compare_apps(req: CompareRequest):
    results = []
    for item in req.apps[:5]:
        try:
            store = item.get("store", "playstore")
            app_id = item["app_id"]
            country = item.get("country", "all")
            if store == "playstore":
                info = await playstore.get_app_info(app_id, country=country)
            else:
                info = await appstore.get_app_info(app_id, country=country)
            aso = score_aso(info)
            results.append({**info.model_dump(), "aso": aso})
        except Exception:
            results.append({"app_id": item.get("app_id"), "error": "Failed to fetch"})
    return results


# ─── AI Analysis (SSE Streaming) ────────────────────────────────

class AnalyzeRequest(BaseModel):
    app_id: str
    store: str = "playstore"
    count: int = 100
    country: str = "all"


@app.post("/api/ai/analyze")
async def analyze_app_reviews_stream(req: AnalyzeRequest):
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(400, "GEMINI_API_KEY not configured.")

    async def event_stream():
        store_name = "Play Store" if req.store == "playstore" else "App Store"

        # Step 1: Fetch app info
        yield sse_event({"type": "step", "icon": "search", "msg": f"Looking up app on {store_name}..."})
        try:
            if req.store == "playstore":
                info = await playstore.get_app_info(req.app_id)
            else:
                info = await appstore.get_app_info(req.app_id)
        except Exception as e:
            yield sse_event({"type": "error", "msg": f"App not found: {e}"})
            return

        yield sse_event({"type": "step", "icon": "check", "msg": f"Found: {info.title} by {info.developer}"})
        await asyncio.sleep(0.3)

        # Step 2: Fetch reviews
        yield sse_event({"type": "step", "icon": "download", "msg": f"Fetching up to {req.count} reviews..."})
        try:
            if req.store == "playstore":
                reviews = await playstore.get_reviews(req.app_id, count=req.count, country=req.country)
            else:
                reviews = await appstore.get_reviews(req.app_id, count=req.count, country=req.country)
        except Exception as e:
            yield sse_event({"type": "error", "msg": f"Failed to fetch reviews: {e}"})
            return

        if not reviews:
            yield sse_event({"type": "error", "msg": "No reviews found for this app."})
            return

        avg = sum(r.rating for r in reviews) / len(reviews)
        stars_dist = {}
        for r in reviews:
            stars_dist[r.rating] = stars_dist.get(r.rating, 0) + 1

        yield sse_event({"type": "step", "icon": "docs", "msg": f"Collected {len(reviews)} reviews (avg {avg:.1f} stars)"})
        await asyncio.sleep(0.3)

        # Step 3: Preview stats
        top_words = _extract_common_words(reviews)
        yield sse_event({"type": "step", "icon": "chart", "msg": f"Rating breakdown: " + ", ".join(f"{k}★={v}" for k, v in sorted(stars_dist.items(), reverse=True))})
        await asyncio.sleep(0.2)

        if top_words:
            yield sse_event({"type": "step", "icon": "bulb", "msg": f"Common words: {', '.join(top_words[:8])}"})
            await asyncio.sleep(0.2)

        # Step 4: AI analysis
        yield sse_event({"type": "step", "icon": "brain", "msg": "Sending reviews to AI for deep analysis..."})
        yield sse_event({"type": "step", "icon": "think", "msg": "AI is reading and categorizing each review..."})

        try:
            analysis = await analyze_reviews(reviews, app_name=info.title, api_key=settings.gemini_api_key)
        except Exception as e:
            yield sse_event({"type": "error", "msg": f"AI analysis failed: {e}"})
            return

        yield sse_event({"type": "step", "icon": "sparkle", "msg": f"Sentiment: {analysis.sentiment.get('positive', 0)}% positive, {analysis.sentiment.get('negative', 0)}% negative"})
        await asyncio.sleep(0.2)
        yield sse_event({"type": "step", "icon": "flag", "msg": f"Found {len(analysis.top_topics)} topics, {len(analysis.feature_requests)} feature requests, {len(analysis.bug_reports)} bugs"})
        await asyncio.sleep(0.2)
        yield sse_event({"type": "step", "icon": "rocket", "msg": "Analysis complete!"})

        # Final result
        yield sse_event({
            "type": "result",
            "data": {"app": info.model_dump(), "analysis": analysis.model_dump()},
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _extract_common_words(reviews) -> list[str]:
    stop = {"the","a","an","is","it","i","my","me","to","and","of","in","for","on","this","that","was","but","not","with","have","has","had","are","be","so","no","do","very","just","app","its"}
    word_count: dict[str, int] = {}
    for r in reviews:
        for w in r.text.lower().split():
            w = w.strip(".,!?\"'()[]{}:;")
            if len(w) > 2 and w not in stop:
                word_count[w] = word_count.get(w, 0) + 1
    return [w for w, _ in sorted(word_count.items(), key=lambda x: -x[1])[:12]]


# ─── Revenue ───────────────────────────────────────────────────

@app.get("/api/revenue/overview")
async def revenue_overview():
    results = {}
    if "revenuecat" in connected_providers:
        p = connected_providers["revenuecat"]
        try: results["revenuecat"] = (await RevenueCatClient(p["api_key"], p.get("project_id", "")).get_overview()).model_dump()
        except Exception as e: results["revenuecat"] = {"error": str(e)}
    if "stripe" in connected_providers:
        p = connected_providers["stripe"]
        try: results["stripe"] = (await StripeClient(p["api_key"]).get_overview()).model_dump()
        except Exception as e: results["stripe"] = {"error": str(e)}
    if "click" in connected_providers:
        p = connected_providers["click"]
        try: results["click"] = (await ClickClient(p["merchant_id"], p["service_id"], p["secret_key"]).get_overview()).model_dump()
        except Exception as e: results["click"] = {"error": str(e)}
    if "uzum" in connected_providers:
        p = connected_providers["uzum"]
        try: results["uzum"] = (await UzumClient(p["merchant_id"], p["api_key"]).get_overview()).model_dump()
        except Exception as e: results["uzum"] = {"error": str(e)}
    return results if results else {"message": "No payment providers connected."}


# ─── Security ──────────────────────────────────────────────────

class ScanRequest(BaseModel):
    target_url: str

@app.post("/api/security/scan")
async def security_scan(req: ScanRequest):
    from urllib.parse import urlparse
    import ipaddress
    parsed = urlparse(req.target_url if "://" in req.target_url else f"https://{req.target_url}")
    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise HTTPException(400, "Cannot scan private/internal addresses.")
    except ValueError:
        pass  # hostname, not IP — OK
    if not host or host in ("localhost", "0.0.0.0"):
        raise HTTPException(400, "Invalid scan target.")
    report = await scan_target(req.target_url)
    scan_cache[report.scan_id] = report.model_dump()
    if len(scan_cache) > 50:
        oldest = next(iter(scan_cache))
        del scan_cache[oldest]
    return report.model_dump()

@app.get("/api/security/report/{scan_id}")
async def get_scan_report(scan_id: str):
    if scan_id not in scan_cache:
        raise HTTPException(404, "Scan not found.")
    return scan_cache[scan_id]


# ─── Settings ──────────────────────────────────────────────────

class ConnectProviderRequest(BaseModel):
    provider: str
    credentials: dict

@app.post("/api/settings/connect")
async def connect_provider(req: ConnectProviderRequest):
    valid = ["revenuecat", "stripe", "click", "uzum"]
    if req.provider not in valid:
        raise HTTPException(400, f"Invalid provider.")
    connected_providers[req.provider] = req.credentials
    return {"status": "connected", "provider": req.provider}

@app.delete("/api/settings/disconnect/{provider}")
async def disconnect_provider(provider: str):
    connected_providers.pop(provider, None)
    return {"status": "disconnected", "provider": provider}

@app.get("/api/settings/connections")
async def list_connections():
    return {"connected": list(connected_providers.keys()), "available": ["revenuecat", "stripe", "click", "uzum"]}

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
