import asyncio
import httpx
from backend.models import AppInfo, ReviewItem

ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
ITUNES_REVIEWS = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/page={page}/json"

FALLBACK_COUNTRIES = ["us", "uz", "gb", "ru", "tr", "in", "de", "kz"]


async def get_app_info(app_id: str, country: str = "all") -> AppInfo:
    countries_to_try = FALLBACK_COUNTRIES if country == "all" else [country] + [c for c in FALLBACK_COUNTRIES if c != country]
    is_bundle_id = not app_id.isdigit()
    last_err = None

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for c in countries_to_try:
            try:
                data = {"results": []}
                if is_bundle_id:
                    resp = await client.get(ITUNES_LOOKUP, params={"bundleId": app_id, "country": c})
                    if resp.status_code == 200:
                        data = resp.json()
                    if not data.get("results"):
                        resp = await client.get(ITUNES_LOOKUP, params={"id": app_id, "country": c})
                        if resp.status_code == 200:
                            data = resp.json()
                else:
                    resp = await client.get(ITUNES_LOOKUP, params={"id": app_id, "country": c})
                    if resp.status_code == 200:
                        data = resp.json()
                    if not data.get("results"):
                        resp = await client.get(ITUNES_LOOKUP, params={"bundleId": app_id, "country": c})
                        if resp.status_code == 200:
                            data = resp.json()

                if data.get("results"):
                    r = data["results"][0]
                    return AppInfo(
                        app_id=str(r.get("trackId", app_id)),
                        store="appstore",
                        title=r.get("trackName", ""),
                        developer=r.get("artistName", ""),
                        rating=r.get("averageUserRating"),
                        ratings_count=r.get("userRatingCount"),
                        reviews_count=r.get("userRatingCount"),
                        price=r.get("price", 0),
                        currency=r.get("currency", "USD"),
                        icon_url=r.get("artworkUrl512") or r.get("artworkUrl100"),
                        description=r.get("description"),
                        category=r.get("primaryGenreName"),
                        version=r.get("version"),
                        updated=r.get("currentVersionReleaseDate"),
                        content_rating=r.get("contentAdvisoryRating"),
                        url=r.get("trackViewUrl"),
                    )
            except Exception as e:
                last_err = e
                continue

    raise last_err or ValueError(f"App not found: {app_id}")


async def get_reviews(app_id: str, count: int = 200, country: str = "all") -> list[ReviewItem]:
    countries_to_try = FALLBACK_COUNTRIES if country == "all" else [country] + [c for c in FALLBACK_COUNTRIES if c != country]
    all_reviews = []
    max_pages = min((count // 50) + 1, 10)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for c in countries_to_try:
            page = 1
            while len(all_reviews) < count and page <= max_pages:
                url = ITUNES_REVIEWS.format(country=c, app_id=app_id, page=page)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    break
                entries = data.get("feed", {}).get("entry", [])
                if not entries:
                    break
                for entry in entries:
                    if "im:rating" not in entry:
                        continue
                    all_reviews.append(ReviewItem(
                        review_id=entry.get("id", {}).get("label"),
                        username=entry.get("author", {}).get("name", {}).get("label", "Anonymous"),
                        rating=int(entry.get("im:rating", {}).get("label", 0)),
                        text=entry.get("content", {}).get("label", ""),
                        date=entry.get("updated", {}).get("label"),
                        thumbs_up=int(entry.get("im:voteSum", {}).get("label", 0)),
                    ))
                page += 1
            if all_reviews:
                break

    return all_reviews[:count]


async def _search_single(client: httpx.AsyncClient, query: str, country: str, count: int) -> list[dict]:
    try:
        resp = await client.get(
            ITUNES_SEARCH,
            params={"term": query, "entity": "software", "limit": min(count, 200), "country": country},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "app_id": str(r.get("trackId")),
                "title": r.get("trackName"),
                "developer": r.get("artistName"),
                "rating": r.get("averageUserRating"),
                "icon_url": r.get("artworkUrl512") or r.get("artworkUrl100"),
                "price": r.get("price", 0),
                "store": "appstore",
            }
            for r in data.get("results", [])
        ]
    except Exception:
        return []


async def search_apps(query: str, count: int = 30, country: str = "all") -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        if country == "all":
            tasks = [_search_single(client, query, c, count) for c in FALLBACK_COUNTRIES]
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
                for r in await _search_single(client, query, c, count):
                    if r["app_id"] not in seen:
                        seen.add(r["app_id"])
                        combined.append(r)
            return combined[:count]
