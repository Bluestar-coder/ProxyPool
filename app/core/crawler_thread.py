from __future__ import annotations
import asyncio
import aiohttp
from PyQt6.QtCore import pyqtSignal
from app.core.worker_thread import AsyncWorkerThread
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.quake import QuakeCrawler
from app.core.crawlers.hunter import HunterCrawler
from app.core.crawlers.free_sites import FreeSitesCrawler
from app.db.models import ProxyCandidate


class CrawlerThread(AsyncWorkerThread):
    found = pyqtSignal(int)
    finished = pyqtSignal(list)
    log = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self._config = config

    async def main(self):
        all_candidates: list[ProxyCandidate] = []
        seen: set[tuple] = set()

        async with aiohttp.ClientSession() as session:
            tasks = []
            cfg = self._config

            if cfg.get("fofa", {}).get("enabled"):
                fc = FofaCrawler(cfg["fofa"]["api_key"])
                tasks.append(fc.crawl(session, cfg["fofa"], cfg["fofa"]["limit"]))

            if cfg.get("quake", {}).get("enabled"):
                qc = QuakeCrawler(cfg["quake"]["api_key"])
                tasks.append(qc.crawl(session, cfg["quake"], cfg["quake"]["limit"]))

            if cfg.get("hunter", {}).get("enabled"):
                hc = HunterCrawler(cfg["hunter"]["api_key"])
                tasks.append(hc.crawl(session, cfg["hunter"], cfg["hunter"]["limit"]))

            if cfg.get("free", {}).get("enabled"):
                free_cfg = cfg["free"]
                tasks.append(FreeSitesCrawler().crawl(session, {}, free_cfg.get("limit", 20)))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    self.log.emit(f"[爬虫] 错误: {result}")
                    continue
                for c in result.candidates:
                    key = (c.host, c.port, c.type, c.username)
                    if key not in seen:
                        seen.add(key)
                        all_candidates.append(c)
                if result.quota_exhausted:
                    self.log.emit(f"[爬虫] {result.source} 额度已耗尽")
                self.found.emit(len(all_candidates))

        self.finished.emit(all_candidates)
