import asyncio
from google_play_scraper import app as gp_app, reviews as gp_reviews, search as gp_search, permissions as gp_permissions, Sort
from backend.models import AppInfo, ReviewItem

FALLBACK_COUNTRIES = ["us", "uz", "gb", "ru", "tr", "in", "de", "kz"]


async def _run_sync(func, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(
        None, lambda: func(*args, **kwargs)
    )


async def get_app_info(app_id: str, lang: str = "en", country: str = "all") -> AppInfo:
    countries_to_try = FALLBACK_COUNTRIES if country == "all" else [country] + [c for c in FALLBACK_COUNTRIES if c != country]
    last_err = None

    for c in countries_to_try:
        try:
            data = await _run_sync(gp_app, app_id, lang=lang, country=c)
            if data and data.get("title"):
                return AppInfo(
                    app_id=app_id,
                    store="playstore",
                    title=data.get("title", ""),
                    developer=data.get("developer", ""),
                    rating=data.get("score"),
                    ratings_count=data.get("ratings"),
                    reviews_count=data.get("reviews"),
                    installs=data.get("realInstalls") or data.get("installs"),
                    price=data.get("price", 0),
                    currency=data.get("currency", "USD"),
                    icon_url=data.get("icon"),
                    description=data.get("description"),
                    category=data.get("genre"),
                    version=data.get("version"),
                    updated=data.get("updated"),
                    content_rating=data.get("contentRating"),
                    url=data.get("url"),
                )
        except Exception as e:
            last_err = e
            continue

    raise last_err or Exception(f"App {app_id} not found in any region")


async def get_reviews(
    app_id: str,
    count: int = 200,
    lang: str = "en",
    country: str = "all",
    sort: str = "newest",
) -> list[ReviewItem]:
    sort_map = {"newest": Sort.NEWEST, "rating": Sort.MOST_RELEVANT}
    sort_val = sort_map.get(sort, Sort.NEWEST)

    countries_to_try = FALLBACK_COUNTRIES if country == "all" else [country] + [c for c in FALLBACK_COUNTRIES if c != country]

    all_reviews = []
    for c in countries_to_try:
        token = None
        remaining = count - len(all_reviews)
        try:
            while remaining > 0:
                batch = min(remaining, 200)
                result, token = await _run_sync(
                    gp_reviews, app_id, lang=lang, country=c,
                    sort=sort_val, count=batch, continuation_token=token,
                )
                if not result:
                    break
                for r in result:
                    all_reviews.append(ReviewItem(
                        review_id=r.get("reviewId"),
                        username=r.get("userName", "Anonymous"),
                        rating=r.get("score", 0),
                        text=r.get("content", ""),
                        date=str(r.get("at", "")),
                        thumbs_up=r.get("thumbsUpCount", 0),
                        reply=r.get("replyContent"),
                        reply_date=str(r.get("repliedAt", "")) if r.get("repliedAt") else None,
                    ))
                remaining -= len(result)
                if not token:
                    break
        except Exception:
            pass
        if all_reviews:
            break

    return all_reviews[:count]


async def _search_single(query: str, lang: str, country: str, count: int) -> list[dict]:
    try:
        results = await _run_sync(gp_search, query, lang=lang, country=country, n_hits=count)
        return [
            {
                "app_id": r.get("appId"),
                "title": r.get("title"),
                "developer": r.get("developer"),
                "rating": r.get("score"),
                "installs": r.get("installs"),
                "icon_url": r.get("icon"),
                "price": r.get("price", 0),
                "store": "playstore",
            }
            for r in results if r.get("appId")
        ]
    except Exception:
        return []


async def search_apps(query: str, count: int = 30, lang: str = "en", country: str = "all") -> list[dict]:
    if country == "all":
        tasks = [_search_single(query, lang, c, count) for c in FALLBACK_COUNTRIES]
        results_per_country = await asyncio.gather(*tasks)
        seen = set()
        combined = []
        for results in results_per_country:
            for r in results:
                if r["app_id"] not in seen:
                    seen.add(r["app_id"])
                    combined.append(r)
        return combined[:count]
    else:
        countries = [country] + (["us"] if country != "us" else [])
        seen = set()
        combined = []
        for c in countries:
            for r in await _search_single(query, lang, c, count):
                if r["app_id"] not in seen:
                    seen.add(r["app_id"])
                    combined.append(r)
        return combined[:count]


RISKY_CATEGORIES = {
    "Camera": "high", "Microphone": "high", "Location": "high",
    "Contacts": "high", "Phone": "medium", "SMS": "high",
    "Calendar": "medium", "Identity": "medium",
    "Device ID & call information": "medium",
    "Photos/Media/Files": "low", "Storage": "low",
    "Wi-Fi connection information": "low",
}


async def get_permissions(app_id: str, country: str = "all") -> dict:
    search_country = country if country != "all" else "us"
    try:
        raw = await _run_sync(gp_permissions, app_id, country=search_country)
    except Exception:
        for c in FALLBACK_COUNTRIES:
            try:
                raw = await _run_sync(gp_permissions, app_id, country=c)
                break
            except Exception:
                continue
        else:
            return {"categories": {}, "risk_score": 0, "risk_level": "unknown", "flags": []}

    total_perms = sum(len(v) for v in raw.values())
    flags = []
    risk_points = 0

    for cat, perms in raw.items():
        level = RISKY_CATEGORIES.get(cat)
        if level == "high":
            risk_points += 3 * len(perms)
            flags.append({"category": cat, "level": "high", "permissions": perms})
        elif level == "medium":
            risk_points += 1 * len(perms)
            flags.append({"category": cat, "level": "medium", "permissions": perms})

    risk_score = min(risk_points, 100)
    if risk_score >= 30:
        risk_level = "high"
    elif risk_score >= 15:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "categories": raw,
        "total_permissions": total_perms,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "flags": sorted(flags, key=lambda f: {"high": 0, "medium": 1}.get(f["level"], 2)),
    }


async def get_similar_apps(app_id: str, country: str = "all") -> list[dict]:
    """Get similar apps using Node.js google-play-scraper's similar() function."""
    import subprocess, json, os

    search_country = country if country != "all" else "uz"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "similar_node.js")
    node_modules = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "node_modules")

    def _run():
        env = os.environ.copy()
        env["NODE_PATH"] = node_modules
        result = subprocess.run(
            ["node", script, app_id, search_country, "15"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        return json.loads(result.stdout) if result.stdout.strip() else []

    try:
        return await asyncio.get_running_loop().run_in_executor(None, _run)
    except Exception:
        return []
