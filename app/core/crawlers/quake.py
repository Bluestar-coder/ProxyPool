from __future__ import annotations

import logging

import aiohttp

from app.core.crawlers.base import BaseCrawler, CrawlPage, QuotaExhausted, RateLimited
from app.db.models import ProxyCandidate

logger = logging.getLogger(__name__)

_DEFAULT_QUERY = 'service:"socks5"'
_API_URL = "https://quake.360.net/api/v3/search/quake_service"


class QuakeCrawler(BaseCrawler):
    name = "quake"
    rate_limit = 1.0

    def __init__(
        self,
        api_key: str,
        page_size: int = 100,
        query: str = _DEFAULT_QUERY,
    ) -> None:
        self._api_key = api_key
        self.page_size = page_size
        self.default_query = query

    async def fetch_page(
        self,
        session: aiohttp.ClientSession,
        query: str,
        cursor: object,
    ) -> CrawlPage:
        q = query or self.default_query
        offset = int(cursor) if cursor is not None else 0

        headers = {"X-QuakeToken": self._api_key}
        body = {"query": q, "start": offset, "size": self.page_size}

        async with session.post(_API_URL, json=body, headers=headers) as resp:
            if resp.status == 429:
                raise RateLimited()
            if resp.status != 200:
                raise RuntimeError(f"Quake HTTP {resp.status}")

            data = await resp.json()

        code = data.get("code", -1)
        if code != 0:
            msg = data.get("message", "")
            logger.warning("Quake error (key=***): code=%s %s", code, msg)
            raise QuotaExhausted(msg)

        records: list[dict] = data.get("data", [])
        items = [
            ProxyCandidate(
                host=r["ip"],
                port=int(r["port"]),
                type="socks5",
                source=self.name,
            )
            for r in records
            if "ip" in r and "port" in r
        ]

        next_cursor = offset + self.page_size if len(records) == self.page_size else None
        return CrawlPage(items=items, next_cursor=next_cursor)
