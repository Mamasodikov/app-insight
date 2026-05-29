import httpx
from backend.models import RevenueOverview

BASE_URL = "https://api.revenuecat.com/v2"


class RevenueCatClient:
    def __init__(self, api_key: str, project_id: str = ""):
        self.api_key = api_key
        self.project_id = project_id
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}{path}", headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_overview(self) -> RevenueOverview:
        try:
            metrics = await self._get(f"/projects/{self.project_id}/metrics/overview")
            data = metrics.get("metrics", metrics)
            return RevenueOverview(
                provider="revenuecat",
                total_revenue=data.get("revenue", 0),
                mrr=data.get("mrr", 0),
                active_subscribers=data.get("active_subscribers", 0),
                trials=data.get("active_trials", 0),
                currency="USD",
            )
        except httpx.HTTPStatusError:
            # Fallback: try listing subscribers for basic data
            return RevenueOverview(provider="revenuecat", total_revenue=0, currency="USD")

    async def get_subscriber(self, app_user_id: str) -> dict:
        return await self._get(f"/projects/{self.project_id}/subscribers/{app_user_id}")

    async def list_subscribers(self, limit: int = 20) -> list[dict]:
        data = await self._get(
            f"/projects/{self.project_id}/subscribers",
            params={"limit": limit},
        )
        return data.get("subscribers", [])

    async def get_transactions(self, limit: int = 50) -> list[dict]:
        try:
            data = await self._get(
                f"/projects/{self.project_id}/transactions",
                params={"limit": limit},
            )
            return data.get("transactions", [])
        except Exception:
            return []
