from __future__ import annotations

import asyncio
import base64
import copy
import json
import shutil
import tempfile
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen

import aiohttp
import yaml
from PyQt6.QtCore import pyqtSignal

from app.core.mihomo_manager import MihomoProcess, _find_free_port, ensure_binary
from app.core.worker_thread import AsyncWorkerThread
from app.db.models import Proxy

_DELAY_URL = "http://www.gstatic.com/generate_204"
# Clash-compatible User-Agent; many providers reject Python's default UA
_CLASH_UA = "ClashMeta/1.18.0"


async def _fetch_url(url: str) -> str:
    """Fetch a subscription URL. Handles http/https and file://."""
    if url.startswith("file://"):
        def _read_file(u: str) -> str:
            with urlopen(u, timeout=20) as f:
                return f.read().decode("utf-8", errors="replace")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read_file, url)
    headers = {
        "User-Agent": _CLASH_UA,
        "Accept": "application/yaml,text/plain,*/*",
    }
    async with aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as session:
        async with session.get(url) as resp:
            return await resp.text(encoding="utf-8", errors="replace")


_DELAY_TIMEOUT_MS = 5000


def _parse_subscription(text: str) -> list[dict]:
    if not text.strip():
        return []

    # Attempt base64 decode if it looks encoded (no newlines or YAML markers)
    candidate = text.strip()
    if "proxies:" not in candidate:
        try:
            decoded = base64.b64decode(candidate + "==").decode("utf-8", errors="replace")
            if "proxies:" in decoded:
                candidate = decoded
        except Exception:
            pass

    try:
        data = yaml.safe_load(candidate)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []

    proxies = data.get("proxies") or []
    if not isinstance(proxies, list):
        return []

    return [p for p in proxies if isinstance(p, dict)]


def _username_for(config: dict) -> str:
    t = config.get("type", "")
    if t == "vmess":
        return config.get("uuid", "")
    if t in ("trojan", "ss"):
        return config.get("password", "")
    return config.get("username", "")


def _password_for(config: dict) -> str:
    t = config.get("type", "")
    # vmess/trojan/ss store their auth credential as username; no separate password
    if t in ("vmess", "trojan", "ss"):
        return ""
    return config.get("password", "")


@dataclass
class SubscriptionResult:
    name: str
    host: str
    port: int
    proxy_type: str
    latency_ms: float
    success: bool


async def test_proxies(
    configs: list[dict],
    api_port: int,
    log_cb: Callable[[str], None],
    concurrency: int = 20,
) -> list[SubscriptionResult]:
    sem = asyncio.Semaphore(concurrency)
    done_count = 0
    total = len(configs)

    async def _test_one(cfg: dict) -> SubscriptionResult:
        nonlocal done_count
        name = cfg.get("name", "")
        host = cfg.get("server", "")
        port = int(cfg.get("port") or 0)
        proxy_type = cfg.get("type", "")
        encoded_name = quote(name, safe="")
        url = (
            f"http://127.0.0.1:{api_port}/proxies/{encoded_name}/delay"
            f"?url={quote(_DELAY_URL, safe=':/')}&timeout={_DELAY_TIMEOUT_MS}"
        )
        async with sem:
            try:
                loop = asyncio.get_running_loop()
                resp_bytes = await loop.run_in_executor(
                    None,
                    lambda: urlopen(url, timeout=(_DELAY_TIMEOUT_MS / 1000) + 2).read(),
                )
                data = json.loads(resp_bytes)
                latency_ms = float(data.get("delay", -1))
                success = latency_ms > 0
            except Exception:
                latency_ms = -1.0
                success = False
            finally:
                done_count += 1
                if done_count % 10 == 0 or done_count == total:
                    try:
                        log_cb(f"[订阅] 已测试 {done_count}/{total}")
                    except Exception:
                        pass
        return SubscriptionResult(
            name=name, host=host, port=port,
            proxy_type=proxy_type, latency_ms=latency_ms, success=success,
        )

    tasks = [_test_one(cfg) for cfg in configs]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    # Keep a result for every config (same index), turning exceptions into failed results
    # so that zip(all_configs, results) in the caller stays correctly aligned.
    results: list[SubscriptionResult] = []
    for i, r in enumerate(raw):
        if isinstance(r, SubscriptionResult):
            results.append(r)
        else:
            cfg = configs[i]
            results.append(SubscriptionResult(
                name=cfg.get("name", ""),
                host=cfg.get("server", ""),
                port=int(cfg.get("port") or 0),
                proxy_type=cfg.get("type", ""),
                latency_ms=-1.0,
                success=False,
            ))
    return results


def _build_mihomo_config(configs: list[dict], api_port: int) -> dict:
    names = [c.get("name", "") for c in configs]
    return {
        "mixed-port": 0,
        "log-level": "silent",
        "external-controller": f"127.0.0.1:{api_port}",
        "proxies": configs,
        "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": names}],
        "rules": ["MATCH,PROXY"],
    }


class SubscriptionThread(AsyncWorkerThread):
    log = pyqtSignal(str)
    finished = pyqtSignal(list)

    def __init__(self, urls: list[str], concurrency: int = 20) -> None:
        super().__init__()
        self._urls = urls
        self._concurrency = concurrency

    async def main(self) -> None:
        def _log(msg: str) -> None:
            self.log.emit(msg)

        # --- Fetch and parse all subscription URLs ---
        all_configs: list[dict] = []
        for i, url in enumerate(self._urls):
            try:
                content = await _fetch_url(url)
                configs = _parse_subscription(content)
                if not configs:
                    _log(f"[订阅] 链接 {i + 1}/{len(self._urls)}: 未解析到节点")
                    continue
            except Exception as e:
                _log(f"[订阅] 链接 {i + 1}/{len(self._urls)} 获取失败: {type(e).__name__}")
                continue

            # Prefix names to avoid conflicts across subscriptions
            seen_names: set[str] = {c.get("name", "") for c in all_configs}
            for cfg in configs:
                name = cfg.get("name", "")
                if name in seen_names:
                    cfg = copy.deepcopy(cfg)
                    new_name = f"sub{i}_{name}"
                    if new_name in seen_names:
                        j = 0
                        while f"{new_name}_{j}" in seen_names:
                            j += 1
                        new_name = f"{new_name}_{j}"
                    cfg["name"] = new_name
                seen_names.add(cfg.get("name", ""))
                all_configs.append(cfg)

            _log(f"[订阅] 链接 {i + 1}/{len(self._urls)} 解析 {len(configs)} 个节点")

        if not all_configs:
            _log("[订阅] 无有效节点，跳过延时测试")
            self.finished.emit([])
            return

        # --- Ensure mihomo binary ---
        ok = await ensure_binary(_log)
        if not ok:
            _log("[订阅] mihomo 内核不可用，终止")
            self.finished.emit([])
            return

        # --- Start mihomo with temp config ---
        tmp_dir = tempfile.mkdtemp(prefix="proxypool_sub_")
        mihomo: list[MihomoProcess] = []  # list used as mutable cell for finally cleanup
        try:
            api_port = _find_free_port()
            config = _build_mihomo_config(all_configs, api_port)
            config_path = f"{tmp_dir}/config.yaml"
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True)

            proc = MihomoProcess(config_path, api_port)
            mihomo.append(proc)
            started = await asyncio.get_running_loop().run_in_executor(
                None, lambda: proc.start(timeout=5.0)
            )
            if not started:
                _log("[订阅] mihomo 启动失败")
                self.finished.emit([])
                return

            # Use the potentially-updated port after TOCTOU retry
            api_port = proc.api_port

            _log(f"[订阅] 开始测试 {len(all_configs)} 个节点...")
            results = await test_proxies(all_configs, api_port, _log, self._concurrency)

        finally:
            for p in mihomo:
                p.stop()
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # --- Convert to Proxy objects ---
        proxies: list[Proxy] = []
        for cfg, result in zip(all_configs, results):
            proxies.append(Proxy(
                host=result.host,
                port=result.port,
                type=result.proxy_type,
                username=_username_for(cfg),
                password=_password_for(cfg),
                latency=result.latency_ms,
                status="valid" if result.success else "invalid",
                source="subscription",
            ))

        valid_count = sum(1 for p in proxies if p.status == "valid")
        _log(f"[订阅] 完成，有效 {valid_count}/{len(proxies)} 个节点")
        self.finished.emit(proxies)
