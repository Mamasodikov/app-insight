import hashlib
import httpx
from datetime import datetime, timedelta
from backend.models import RevenueOverview


class ClickClient:
    """Click.uz Merchant API client."""

    BASE_URL = "https://api.click.uz/v2/merchant"

    def __init__(self, merchant_id: str, service_id: str, secret_key: str):
        self.merchant_id = merchant_id
        self.service_id = service_id
        self.secret_key = secret_key
        self._auth_header = self._make_auth()

    def _make_auth(self) -> str:
        timestamp = str(int(datetime.utcnow().timestamp()))
        digest = hashlib.sha1(f"{timestamp}{self.secret_key}".encode()).hexdigest()
        return f"{self.merchant_id}:{digest}:{timestamp}"

    async def _get(self, path: str, params: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}{path}",
                headers={
                    "Auth": self._auth_header,
                    "Content-Type": "application/json",
                },
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_overview(self) -> RevenueOverview:
        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)

        try:
            data = await self._get(
                f"/payment/list/{self.service_id}",
                params={
                    "from_date": month_ago.strftime("%Y-%m-%d"),
                    "to_date": now.strftime("%Y-%m-%d"),
                },
            )
            payments = data.get("payments", [])
            total = sum(p.get("amount", 0) for p in payments if p.get("status") == 2)

            transactions = [
                {
                    "id": str(p.get("payment_id")),
                    "amount": p.get("amount", 0),
                    "status": "paid" if p.get("status") == 2 else "pending",
                    "date": p.get("create_time", ""),
                    "description": p.get("merchant_trans_id", ""),
                }
                for p in payments[:20]
            ]

            return RevenueOverview(
                provider="click",
                total_revenue=total,
                transactions=transactions,
                currency="UZS",
            )
        except Exception:
            return RevenueOverview(provider="click", total_revenue=0, currency="UZS")


class UzumClient:
    """Uzum (formerly Apelsin) payment API client."""

    BASE_URL = "https://api.uzum.uz/v1"

    def __init__(self, merchant_id: str, api_key: str):
        self.merchant_id = merchant_id
        self.api_key = api_key

    async def _get(self, path: str, params: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body or {},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_overview(self) -> RevenueOverview:
        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)

        try:
            data = await self._post("/merchant/transactions", body={
                "merchant_id": self.merchant_id,
                "from": month_ago.strftime("%Y-%m-%dT00:00:00Z"),
                "to": now.strftime("%Y-%m-%dT23:59:59Z"),
            })
            txns = data.get("transactions", [])
            total = sum(t.get("amount", 0) for t in txns if t.get("state") == "COMPLETED")

            transactions = [
                {
                    "id": t.get("id"),
                    "amount": t.get("amount", 0),
                    "status": t.get("state", "unknown").lower(),
                    "date": t.get("created_at", ""),
                    "description": t.get("description", ""),
                }
                for t in txns[:20]
            ]

            return RevenueOverview(
                provider="uzum",
                total_revenue=total,
                transactions=transactions,
                currency="UZS",
            )
        except Exception:
            return RevenueOverview(provider="uzum", total_revenue=0, currency="UZS")
