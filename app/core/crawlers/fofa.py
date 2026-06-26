from __future__ import annotations

import base64
import logging

import aiohttp

from app.core.crawlers.base import BaseCrawler, CrawlPage, QuotaExhausted, RateLimited
from app.db.models import ProxyCandidate

logger = logging.getLogger(__name__)

_DEFAULT_QUERY = 'protocol=="socks5" && "Version:5 Method:No Authentication(0x00)"'
_API_URL = "https://fofa.info/api/v1/search/all"


class FofaCrawler(BaseCrawler):
    name = "fofa"
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
        page = int(cursor) if cursor is not None else 1
        encoded = base64.b64encode(q.encode()).decode()

        params = {
            "key": self._api_key,
            "qbase64": encoded,
            "fields": "ip,port,protocol,country_name",
            "size": self.page_size,
            "page": page,
        }

        async with session.get(_API_URL, params=params) as resp:
            if resp.status == 429:
                raise RateLimited()
            if resp.status != 200:
                raise RuntimeError(f"Fofa HTTP {resp.status}")

            data = await resp.json()

        if data.get("error"):
            errmsg = data.get("errmsg", "")
            logger.warning("Fofa error (key=***): %s", errmsg)
            raise QuotaExhausted(errmsg)

        results: list[list] = data.get("results", [])
        items = [
            ProxyCandidate(
                host=row[0],
                port=int(row[1]),
                type=row[2] if len(row) > 2 else "socks5",
                source=self.name,
            )
            for row in results
            if len(row) >= 2
        ]

        next_cursor = page + 1 if len(results) == self.page_size else None
        return CrawlPage(items=items, next_cursor=next_cursor)
