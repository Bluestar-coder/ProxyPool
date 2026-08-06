from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from aiohttp import web
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from app.core.rotator import ProxyRotator
    from app.db.database import Database

_logger = logging.getLogger(__name__)


def _json(data: object, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json",
    )


class RestApiThread(QThread):
    """Lightweight aiohttp REST API server running in its own thread.

    Endpoints
    ---------
    GET  /proxy     current proxy (safe display)
    GET  /proxies   all valid proxies
    GET  /status    pool statistics
    POST /refresh   request a validation run (emits refresh_requested signal)
    """

    refresh_requested = pyqtSignal()

    def __init__(self, rotator: "ProxyRotator", db: "Database",  # pragma: no cover
                 port: int = 51025, parent=None):
        super().__init__(parent)
        self._rotator = rotator
        self._db = db
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_proxy(self, request: web.Request) -> web.Response:
        proxy = self._rotator.get_current()
        if proxy is None:
            return _json({"error": "no valid proxy"}, status=503)
        return _json({
            "host": proxy.host,
            "port": proxy.port,
            "type": proxy.type,
            "address": f"{proxy.host}:{proxy.port}",
            "region": proxy.region,
            "latency_ms": proxy.latency,
            "speed_kbps": proxy.speed,
        })

    async def _handle_proxies(self, request: web.Request) -> web.Response:
        proxies = self._db.get_all_proxies(status="valid")
        return _json([
            {
                "host": p.host,
                "port": p.port,
                "type": p.type,
                "address": f"{p.host}:{p.port}",
                "region": p.region,
                "latency_ms": p.latency,
                "speed_kbps": p.speed,
                "anonymity": p.anonymity,
                "success_rate": (
                    round(p.use_count / (p.use_count + p.fail_count), 3)
                    if (p.use_count + p.fail_count) > 0 else None
                ),
            }
            for p in proxies
        ])

    async def _handle_status(self, request: web.Request) -> web.Response:
        total   = self._db.count_proxies()
        valid   = self._db.count_proxies(status="valid")
        invalid = self._db.count_proxies(status="invalid")
        unknown = self._db.count_proxies(status="unknown")
        current = self._rotator.get_current()
        return _json({
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "unknown": unknown,
            "current_proxy": f"{current.host}:{current.port}" if current else None,
        })

    async def _handle_refresh(self, request: web.Request) -> web.Response:
        self.refresh_requested.emit()
        return _json({"ok": True, "message": "validation triggered"})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self):  # pragma: no cover
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):  # pragma: no cover
        app = web.Application()
        app.router.add_get("/proxy", self._handle_proxy)
        app.router.add_get("/proxies", self._handle_proxies)
        app.router.add_get("/status", self._handle_status)
        app.router.add_post("/refresh", self._handle_refresh)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self._port)
        try:
            await site.start()
            _logger.info("REST API listening on http://127.0.0.1:%d", self._port)
            while not self.isInterruptionRequested():
                await asyncio.sleep(0.2)
        finally:
            await self._runner.cleanup()

    def stop(self):  # pragma: no cover
        self.requestInterruption()
        self.wait(3000)
