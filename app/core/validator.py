from __future__ import annotations

import asyncio
import time

import aiohttp
from aiohttp_socks import ProxyConnector
from PyQt6.QtCore import pyqtSignal

from app.core.worker_thread import AsyncWorkerThread
from app.db.models import Proxy, ValidationResult

# TTL cache for region lookups: ip -> (region_str, monotonic_timestamp)
_region_cache: dict[str, tuple[str, float]] = {}
_REGION_TTL = 3600.0


async def _get_local_ip() -> str:
    """Fetch the machine's public IP address via an external service."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.ipify.org", timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            return (await resp.text()).strip()


async def _get_region(ip: str) -> str:
    """Return country + region for an IP, with TTL caching."""
    now = time.monotonic()
    if ip in _region_cache:
        value, ts = _region_cache[ip]
        if now - ts < _REGION_TTL:
            return value

    try:
        url = f"http://ip-api.com/json/{ip}?fields=country,regionName"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
        country = data.get("country", "")
        region_name = data.get("regionName", "")
        region = " ".join(filter(None, [country, region_name]))
        _region_cache[ip] = (region, now)
        return region
    except Exception:
        return ""


def _detect_anonymity(response_ip: str, proxy_ip: str, local_ip: str) -> str:
    """Classify proxy anonymity based on the IP visible to the validation endpoint."""
    if local_ip and local_ip in response_ip:
        return "transparent"
    if proxy_ip and proxy_ip in response_ip:
        return "medium"
    return "high"


async def validate_single(
    proxy: Proxy,
    endpoint: str,
    timeout: int,
    backup_endpoint: str = "",
) -> ValidationResult:
    """Validate a single proxy: connection test + anonymity detection + region lookup."""
    start = time.monotonic()

    try:
        local_ip = await _get_local_ip()
        connector = ProxyConnector.from_url(proxy.url)
        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(
                    endpoint, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    data = await resp.json()
                used_endpoint = endpoint
            except Exception:
                if not backup_endpoint:
                    raise
                async with session.get(
                    backup_endpoint, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    data = await resp.json()
                used_endpoint = backup_endpoint

        latency = time.monotonic() - start
        response_ip: str = data.get("origin", "")
        anonymity = _detect_anonymity(response_ip, proxy.host, local_ip)
        region = await _get_region(proxy.host)

        return ValidationResult(
            proxy_id=proxy.id,
            success=True,
            latency=latency,
            anonymity=anonymity,
            region=region,
            endpoint=used_endpoint,
        )

    except Exception as e:
        return ValidationResult(
            proxy_id=proxy.id,
            success=False,
            latency=-1.0,
            anonymity="",
            region="",
            error=type(e).__name__,
        )


class ValidatorThread(AsyncWorkerThread):
    progress = pyqtSignal(int, int)    # done, total
    result_ready = pyqtSignal(object)  # ValidationResult
    finished = pyqtSignal()

    def __init__(
        self,
        proxies: list[Proxy],
        endpoint: str,
        backup_endpoint: str,
        timeout: int,
        concurrency: int,
    ) -> None:
        super().__init__()
        self.proxies = proxies
        self.endpoint = endpoint
        self.backup_endpoint = backup_endpoint
        self.timeout = timeout
        self.concurrency = concurrency

    async def main(self) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(self.proxies)
        done = 0

        async def _validate(proxy: Proxy) -> None:
            nonlocal done
            async with semaphore:
                result = await validate_single(
                    proxy, self.endpoint, self.timeout, self.backup_endpoint
                )
                self.result_ready.emit(result)
                done += 1
                if done % 20 == 0:
                    self.progress.emit(done, total)

        await asyncio.gather(*[_validate(p) for p in self.proxies])
        self.progress.emit(done, total)
        self.finished.emit()
