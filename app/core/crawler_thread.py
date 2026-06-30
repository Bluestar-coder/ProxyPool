from __future__ import annotations
import asyncio
import aiohttp
from PyQt6.QtCore import pyqtSignal
from app.core.worker_thread import AsyncWorkerThread
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.free_sites import FreeSitesCrawler
from app.db.models import CrawlerResult, ProxyCandidate

_SOURCE_TIMEOUT = 90.0   # per-source hard cap (seconds)
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=8)


async def _run_source(name: str, coro) -> CrawlerResult:
    try:
        return await asyncio.wait_for(coro, timeout=_SOURCE_TIMEOUT)
    except asyncio.TimeoutError:
        return CrawlerResult(source=name, errors=[f"{name} timed out after {int(_SOURCE_TIMEOUT)}s"])


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
        cfg = self._config

        async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
            task_pairs: list[tuple[str, object]] = []

            if cfg.get("fofa", {}).get("enabled"):
                api_key = cfg["fofa"]["api_key"]
                limit = cfg["fofa"]["limit"]
                queries = cfg["fofa"].get("queries") or [cfg["fofa"].get("query", "")]
                queries = [q for q in queries if q]
                for i, q in enumerate(queries, 1):
                    label = f"fofa:{i}" if len(queries) > 1 else "fofa"
                    task_pairs.append((label, FofaCrawler(api_key).crawl(
                        session, {"query": q}, limit
                    )))

            if cfg.get("free", {}).get("enabled"):
                free_cfg = cfg["free"]
                task_pairs.append(("free_sites", FreeSitesCrawler().crawl(session, {}, free_cfg.get("limit", 50))))

            if not task_pairs:
                self.log.emit("[爬虫] 未启用任何来源，请在对话框中勾选至少一个")
                self.finished.emit([])
                return

            for name, _ in task_pairs:
                self.log.emit(f"[爬虫] 启动: {name}")

            results = await asyncio.gather(
                *[_run_source(name, coro) for name, coro in task_pairs],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, BaseException):
                    self.log.emit(f"[爬虫] 未预期错误: {type(result).__name__}: {result}")
                    continue
                if result.errors:
                    for err in result.errors:
                        self.log.emit(f"[爬虫] {result.source}: {err}")
                for c in result.candidates:
                    key = (c.host, c.port, c.type, c.username)
                    if key not in seen:
                        seen.add(key)
                        all_candidates.append(c)
                if result.quota_exhausted:
                    self.log.emit(f"[爬虫] {result.source} 配额已耗尽")
                self.log.emit(f"[爬虫] {result.source} 完成，获取 {len(result.candidates)} 个候选")
                self.found.emit(len(all_candidates))

        self.finished.emit(all_candidates)
