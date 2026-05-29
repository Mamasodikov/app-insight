import httpx
from datetime import datetime, timedelta
from backend.models import RevenueOverview

BASE_URL = "https://api.stripe.com/v1"


class StripeClient:
    def __init__(self, secret_key: str):
        self.secret_key = secret_key

    async def _get(self, path: str, params: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{BASE_URL}{path}",
                params=params,
                auth=(self.secret_key, ""),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_overview(self) -> RevenueOverview:
        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)

        # Get recent charges
        charges = await self._get("/charges", params={
            "limit": 100,
            "created[gte]": int(month_ago.timestamp()),
        })

        total = sum(c.get("amount", 0) for c in charges.get("data", []) if c.get("paid")) / 100

        # Get active subscriptions count
        subs = await self._get("/subscriptions", params={
            "status": "active",
            "limit": 1,
        })

        # Get balance
        balance = await self._get("/balance")
        available = sum(b.get("amount", 0) for b in balance.get("available", [])) / 100

        transactions = []
        for c in charges.get("data", [])[:20]:
            transactions.append({
                "id": c.get("id"),
                "amount": c.get("amount", 0) / 100,
                "currency": c.get("currency", "usd"),
                "status": "paid" if c.get("paid") else "failed",
                "description": c.get("description", ""),
                "date": datetime.fromtimestamp(c.get("created", 0)).isoformat(),
                "customer": c.get("customer"),
            })

        return RevenueOverview(
            provider="stripe",
            total_revenue=total,
            mrr=total,  # approximation
            active_subscribers=subs.get("total_count", 0) if "total_count" in subs else None,
            transactions=transactions,
            currency="USD",
        )

    async def get_customers(self, limit: int = 20) -> list[dict]:
        data = await self._get("/customers", params={"limit": limit})
        return data.get("data", [])

    async def get_subscriptions(self, status: str = "active", limit: int = 50) -> list[dict]:
        data = await self._get("/subscriptions", params={"status": status, "limit": limit})
        return data.get("data", [])
