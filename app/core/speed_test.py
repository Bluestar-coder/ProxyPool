"""Speed test for proxies - measures download throughput."""
from __future__ import annotations

import asyncio
import time

import aiohttp
from aiohttp_socks import ProxyConnector
from PyQt6.QtCore import pyqtSignal

from app.core.worker_thread import AsyncWorkerThread
from app.db.models import Proxy

# Speed test URLs - Cloudflare is most reliable, others as fallback
_SPEED_TEST_URLS = [
    "http://speed.cloudflare.com/__down?bytes=102400",  # Cloudflare 100KB
    "http://httpbin.org/bytes/102400",                   # httpbin 100KB
    "http://cachefly.cachefly.net/10mb.test",           # CacheFly CDN
]

_TARGET_BYTES = 100 * 1024  # Download 100KB for speed test

SPEED_TEST_TIMEOUT_SECS = 20  # budget for one measure_speed() call (all fallback URLs)


async def _try_speed_urls(session: aiohttp.ClientSession, timeout: int) -> float:
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    for url in _SPEED_TEST_URLS:
        try:
            downloaded = 0
            start = time.monotonic()
            async with session.get(url, timeout=req_timeout) as resp:
                if resp.status != 200:
                    continue
                # Stream download until we have enough data
                async for chunk in resp.content.iter_chunked(8192):
                    downloaded += len(chunk)
                    if downloaded >= _TARGET_BYTES:
                        break
            elapsed = time.monotonic() - start
            # Verify we got enough data (not blocked/redirected)
            if elapsed <= 0 or downloaded < _TARGET_BYTES * 0.5:
                continue
            return round((downloaded / 1024) / elapsed, 1)
        except Exception:
            continue
    return -1.0


async def measure_speed(
    proxy_url: str,
    timeout: int = SPEED_TEST_TIMEOUT_SECS,
    session: aiohttp.ClientSession | None = None,
) -> float:
    """Measure proxy speed (Clash-style). Returns KB/s or -1 on failure.

    Pass an already-connected `session` (e.g. one a caller opened for its
    own connectivity check against the same proxy) to avoid establishing a
    second TCP/SOCKS connection just for the speed test.
    """
    if session is not None:
        return await _try_speed_urls(session, timeout)
    try:
        connector = ProxyConnector.from_url(proxy_url)
        client_timeout = aiohttp.ClientTimeout(total=timeout, connect=10)
        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as new_session:
            return await _try_speed_urls(new_session, timeout)
    except Exception:
        return -1.0


class SpeedTestThread(AsyncWorkerThread):
    progress = pyqtSignal(int, int)      # done, total
    result_ready = pyqtSignal(int, float)  # proxy_id, speed_kbps
    finished = pyqtSignal()

    def __init__(self, proxies: list[Proxy], concurrency: int = 20) -> None:
        super().__init__()
        self.proxies = proxies
        self.concurrency = concurrency

    async def main(self) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(self.proxies)
        done = 0

        async def _test(proxy: Proxy) -> None:
            nonlocal done
            async with semaphore:
                speed = await measure_speed(proxy.url)
                self.result_ready.emit(proxy.id, speed)
                done += 1
                if done % 5 == 0 or done == total:
                    self.progress.emit(done, total)

        await asyncio.gather(*[_test(p) for p in self.proxies])
        self.finished.emit()
