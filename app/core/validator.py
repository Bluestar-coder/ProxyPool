from __future__ import annotations

import asyncio
import json as _json
import re
import time

import aiohttp
from aiohttp_socks import ProxyConnector
from opencc import OpenCC
from PyQt6.QtCore import pyqtSignal

from app.core.worker_thread import AsyncWorkerThread
from app.core.speed_test import measure_speed, SPEED_TEST_TIMEOUT_SECS
from app.db.models import Proxy, ValidationResult

_region_cache: dict[str, tuple[str, float]] = {}
_REGION_TTL = 3600.0
_IP_API_BATCH = 100  # ip-api.com free-tier limit per request
_t2s = OpenCC("t2s")  # Traditional to Simplified Chinese

_VALIDATION_ENDPOINTS = [
    "http://ip-api.com/json",
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "http://ip.sb/ip",
]


async def _get_local_ip() -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.ipify.org", timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            return (await resp.text()).strip()


async def _batch_region_lookup(ips: list[str]) -> dict[str, str]:
    """Batch region lookup for a list of IPs using ip-api.com/batch.

    Skips IPs already in cache. Groups uncached into batches of 100.
    Returns {ip: region_string}.
    """
    results: dict[str, str] = {}
    now = time.monotonic()

    uncached: list[str] = []
    for ip in ips:
        cached_val, cached_ts = _region_cache.get(ip, ("", 0.0))
        if cached_val and (now - cached_ts) < _REGION_TTL:
            results[ip] = cached_val
        else:
            uncached.append(ip)

    if not uncached:
        return results

    async with aiohttp.ClientSession() as session:
        for i in range(0, len(uncached), _IP_API_BATCH):
            batch = uncached[i : i + _IP_API_BATCH]
            try:
                payload = [
                    {"query": ip, "fields": "country,regionName,query"}
                    for ip in batch
                ]
                async with session.post(
                    "http://ip-api.com/batch?lang=zh-CN",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                fetch_time = time.monotonic()
                for item in data:
                    ip = item.get("query", "")
                    if not ip:
                        continue
                    country = item.get("country", "")
                    region_name = item.get("regionName", "")
                    region = " ".join(filter(None, [country, region_name]))
                    region = _t2s.convert(region)  # Convert to simplified Chinese
                    _region_cache[ip] = (region, fetch_time)
                    results[ip] = region
            except Exception:
                for ip in batch:
                    results[ip] = ""

    return results


def _extract_ip(data: dict) -> str:
    """Extract IP from httpbin /ip, ip-api.com /json, or ipify /json response."""
    return data.get("origin") or data.get("query") or data.get("ip") or ""


def _detect_anonymity(response_ip: str, proxy_ip: str, local_ip: str) -> str:
    if local_ip and local_ip in response_ip:
        return "transparent"
    if proxy_ip and proxy_ip in response_ip:
        return "medium"
    return "high"


_IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def _is_valid_ip(s: str) -> bool:
    """Check if string looks like an IPv4 address."""
    return bool(_IP_PATTERN.match(s.strip()))


async def validate_single(
    proxy: Proxy,
    endpoints: list[str],
    timeout: int,
    local_ip: str,
    test_speed: bool = True,
) -> ValidationResult:
    """Connectivity check using multiple endpoints. Region is filled in batch."""
    last_error = ""
    try:
        connector = ProxyConnector.from_url(proxy.url)
        async with aiohttp.ClientSession(connector=connector) as session:
            for endpoint in endpoints:
                try:
                    start = time.monotonic()  # Reset timer for each endpoint
                    async with session.get(
                        endpoint, timeout=aiohttp.ClientTimeout(total=timeout)
                    ) as resp:
                        if resp.status != 200:
                            last_error = f"HTTP{resp.status}"
                            continue
                        text = await resp.text()
                        try:
                            data = _json.loads(text)
                        except Exception:
                            data = {"origin": text.strip()}

                    latency_ms = (time.monotonic() - start) * 1000  # Convert to ms
                    response_ip = _extract_ip(data) or text.strip()
                    if not _is_valid_ip(response_ip):
                        last_error = "InvalidResponse"
                        continue

                    anonymity = _detect_anonymity(response_ip, proxy.host, local_ip)

                    # Measure speed after successful validation, reusing this
                    # session so we don't open a second connection to the proxy.
                    speed = -1.0
                    if test_speed:
                        speed = await measure_speed(
                            proxy.url, timeout=SPEED_TEST_TIMEOUT_SECS, session=session
                        )

                    return ValidationResult(
                        proxy_id=proxy.id,
                        success=True,
                        latency=latency_ms,
                        anonymity=anonymity,
                        region="",
                        speed=speed,
                        endpoint=endpoint,
                    )
                except Exception as e:
                    last_error = type(e).__name__
                    continue
    except Exception as e:
        last_error = type(e).__name__

    return ValidationResult(
        proxy_id=proxy.id,
        success=False,
        latency=-1.0,
        anonymity="",
        region="",
        error=last_error,
    )


class ValidatorThread(AsyncWorkerThread):
    progress = pyqtSignal(int, int)    # done, total
    result_ready = pyqtSignal(object)  # ValidationResult (region="" until phase 2)
    regions_ready = pyqtSignal(dict)   # {proxy_id: region} after batch lookup
    finished = pyqtSignal()

    def __init__(
        self,
        proxies: list[Proxy],
        endpoint: str = "",
        backup_endpoint: str = "",
        timeout: int = 15,
        concurrency: int = 50,
    ) -> None:
        super().__init__()
        self.proxies = proxies
        self.endpoints = _VALIDATION_ENDPOINTS.copy()
        if endpoint and endpoint not in self.endpoints:
            self.endpoints.insert(0, endpoint)
        if backup_endpoint and backup_endpoint not in self.endpoints:
            self.endpoints.append(backup_endpoint)
        self.timeout = timeout
        self.concurrency = concurrency

    async def main(self) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)
        total = len(self.proxies)
        done = 0
        # Worst case: every endpoint times out before one succeeds, plus the
        # speed test budget for the one that does, plus a teardown margin.
        hard_timeout = len(self.endpoints) * self.timeout + SPEED_TEST_TIMEOUT_SECS + 5

        try:
            local_ip = await _get_local_ip()
        except Exception:
            local_ip = ""

        id_to_host: dict[int, str] = {p.id: p.host for p in self.proxies}
        valid_ids: list[int] = []

        async def _validate(proxy: Proxy) -> None:
            nonlocal done
            async with semaphore:
                try:
                    result = await asyncio.wait_for(
                        validate_single(
                            proxy, self.endpoints, self.timeout, local_ip,
                        ),
                        timeout=hard_timeout,
                    )
                except asyncio.TimeoutError:
                    result = ValidationResult(
                        proxy_id=proxy.id,
                        success=False,
                        latency=-1.0,
                        anonymity="",
                        region="",
                        error="HardTimeout",
                    )
                self.result_ready.emit(result)
                if result.success:
                    valid_ids.append(proxy.id)
                done += 1
                if done % 10 == 0 or done == total:
                    self.progress.emit(done, total)

        # Phase 1: parallel connectivity check. return_exceptions=True so one
        # proxy's unexpected failure can't abort the whole batch and silently
        # skip Phase 2 / the finished signal.
        await asyncio.gather(*[_validate(p) for p in self.proxies], return_exceptions=True)

        # Phase 2: batch region lookup for valid proxies only
        if valid_ids:
            valid_ips = list({id_to_host[pid] for pid in valid_ids if pid in id_to_host})
            try:
                region_map = await _batch_region_lookup(valid_ips)
                proxy_regions: dict[int, str] = {
                    pid: region_map.get(id_to_host.get(pid, ""), "")
                    for pid in valid_ids
                    if region_map.get(id_to_host.get(pid, ""), "")
                }
                if proxy_regions:
                    self.regions_ready.emit(proxy_regions)
            except Exception:
                pass  # region enrichment is best-effort

        self.finished.emit()
