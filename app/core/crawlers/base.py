from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import aiohttp

from app.db.models import CrawlerResult, ProxyCandidate

logger = logging.getLogger(__name__)


class RateLimited(Exception):
    def __init__(self, retry_after: float = 5.0) -> None:
        super().__init__(f"Rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


class QuotaExhausted(Exception):
    pass


@dataclass
class CrawlPage:
    items: list[ProxyCandidate] = field(default_factory=list)
    next_cursor: object = None


class BaseCrawler(ABC):
    name: str = "base"
    rate_limit: float = 1.0

    @abstractmethod
    async def fetch_page(
        self,
        session: aiohttp.ClientSession,
        query: str,
        cursor: object,
    ) -> CrawlPage: ...

    async def test_auth(self, session: aiohttp.ClientSession) -> bool:
        return True

    async def crawl(
        self,
        session: aiohttp.ClientSession,
        config: dict,
        limit: int,
    ) -> CrawlerResult:
        query = config.get("query", "")
        candidates: list[ProxyCandidate] = []
        errors: list[str] = []
        quota_exhausted = False
        cursor: object = None

        while True:
            try:
                page = await self.fetch_page(session, query, cursor)
                candidates.extend(page.items)

                if page.next_cursor is None or len(candidates) >= limit:
                    break

                cursor = page.next_cursor
                await asyncio.sleep(self.rate_limit)

            except RateLimited as exc:
                logger.warning("%s rate-limited; sleeping %.1fs", self.name, exc.retry_after)
                await asyncio.sleep(exc.retry_after)

            except QuotaExhausted:
                logger.warning("%s quota exhausted", self.name)
                quota_exhausted = True
                break

            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                logger.error("%s fetch error: %s", self.name, msg)
                errors.append(msg)
                break

        return CrawlerResult(
            source=self.name,
            candidates=candidates[:limit],
            errors=errors,
            quota_exhausted=quota_exhausted,
        )
