"""Тонкий клиент Keitaro Admin API."""
import time

import httpx

from . import config


CACHE_TTL = 30
_SHARED_CACHE: dict = {}


class KeitaroError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"Keitaro {status}: {detail}")
        self.status = status
        self.detail = detail


class KeitaroClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, transport=None):
        self._cache = _SHARED_CACHE
        self._http = httpx.Client(
            base_url=(base_url or config.KEITARO_URL) + "/admin_api/v1",
            headers={"Api-Key": api_key or config.KEITARO_API_KEY},
            timeout=30,
            transport=transport,
        )

    def _req(self, method: str, path: str, **kw):
        r = self._http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except ValueError:
                detail = r.text[:300]
            raise KeitaroError(r.status_code, detail)
        return r.json() if r.content else None

    # справочники
    def domains(self):
        return self._req("GET", "/domains")

    def groups(self, type_: str = "campaigns"):
        return self._req("GET", "/groups", params={"type": type_})

    def traffic_sources(self):
        return self._req("GET", "/traffic_sources")

    def offers(self, search: str | None = None, limit: int = 50, offset: int = 0):
        return self._filtered("/offers", search, limit, offset)

    def offer(self, offer_id: int):
        return self._req("GET", f"/offers/{offer_id}")

    # кампании
    def campaigns(self, search: str | None = None, limit: int = 50, offset: int = 0):
        return self._filtered("/campaigns", search, limit, offset)

    def _filtered(self, path: str, search: str | None, limit: int, offset: int):
        """Keitaro не фильтрует список по названию: забираем всё, ищем сами."""
        rows = self._all(path)
        if search:
            q = search.strip().lower()
            rows = [r for r in rows if q in str(r["id"]) or q in r["name"].lower()]
        return rows[offset: offset + limit]

    def _all(self, path: str):
        hit = self._cache.get(path)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        rows = self._req("GET", path, params={"limit": 1000})
        self._cache[path] = (time.monotonic(), rows)
        return rows

    def invalidate(self):
        self._cache.clear()

    def campaign(self, campaign_id: int):
        return self._req("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict):
        self.invalidate()
        return self._req("POST", "/campaigns", json=payload)

    def delete_campaign(self, campaign_id: int):
        return self._req("DELETE", f"/campaigns/{campaign_id}")

    # потоки
    def streams(self, campaign_id: int):
        return self._req("GET", f"/campaigns/{campaign_id}/streams")

    def create_stream(self, payload: dict):
        return self._req("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict):
        return self._req("PUT", f"/streams/{stream_id}", json=payload)

    # статистика
    def offer_report(self, campaign_id: int, interval: str = "all_time"):
        body = {
            "range": {"interval": interval, "timezone": "Europe/Moscow"},
            "columns": [],
            "metrics": [
                "clicks", "campaign_unique_clicks", "conversions", "sales",
                "revenue", "cost", "profit", "roi", "cr",
            ],
            "grouping": ["offer_id", "offer"],
            "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": campaign_id}],
            "limit": 500,
        }
        return self._req("POST", "/report/build", json=body)
