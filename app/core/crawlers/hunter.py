from __future__ import annotations

import logging

import aiohttp

from app.core.crawlers.base import BaseCrawler, CrawlPage, QuotaExhausted, RateLimited
from app.db.models import ProxyCandidate

logger = logging.getLogger(__name__)

_DEFAULT_QUERY = 'socks5 && "Version:5"'
_API_URL = "https://hunter.qianxin.com/openApi/search"
_QUOTA_EXHAUSTED_CODE = 40205


class HunterCrawler(BaseCrawler):
    name = "hunter"
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

        params = {
            "api-key": self._api_key,
            "search": q,
            "page": page,
            "page_size": self.page_size,
            "asset_type": 0,
        }

        async with session.get(_API_URL, params=params) as resp:
            if resp.status == 429:
                raise RateLimited()
            if resp.status != 200:
                raise RuntimeError(f"Hunter HTTP {resp.status}")

            data = await resp.json()

        code = data.get("code", -1)
        if code == _QUOTA_EXHAUSTED_CODE:
            logger.warning("Hunter quota exhausted (key=***)")
            raise QuotaExhausted()
        if code != 200:
            msg = data.get("message", "")
            logger.warning("Hunter error (key=***): code=%s %s", code, msg)
            raise RuntimeError(f"Hunter error {code}: {msg}")

        arr: list[dict] = (data.get("data") or {}).get("arr", [])
        items = [
            ProxyCandidate(
                host=r["ip"],
                port=int(r["port"]),
                type="socks5",
                source=self.name,
            )
            for r in arr
            if "ip" in r and "port" in r
        ]

        next_cursor = page + 1 if len(arr) == self.page_size else None
        return CrawlPage(items=items, next_cursor=next_cursor)
