from __future__ import annotations

import logging
import threading
import time
from enum import Enum

from app.db.models import Proxy, ProxyEndpoint

_logger = logging.getLogger(__name__)


class RotationMode(Enum):
    ROUND_ROBIN = "round_robin"
    FAILOVER = "failover"
    BY_COUNT = "by_count"
    BY_TIME = "by_time"
    BY_SCENE = "by_scene"
    BY_KEYWORD = "by_keyword"
    FIXED = "fixed"


class ProxyRotator:
    """Six rotation modes. Shared state is protected by threading.RLock so that
    synchronous UI-thread calls (load_proxies, set_mode) and async SOCKS-server
    calls are mutually exclusive without deadlock.
    """

    def __init__(self) -> None:
        self._proxies: list[Proxy] = []
        self._valid: list[Proxy] = []
        self._index: int = 0
        self._mode: RotationMode = RotationMode.ROUND_ROBIN
        self._params: dict = {}
        self._lock: threading.RLock = threading.RLock()
        self._consecutive_success: int = 0
        self._last_switch_time: float = time.monotonic()

    # ------------------------------------------------------------------
    # Configuration (synchronous — called from UI thread before async use)
    # ------------------------------------------------------------------

    def load_proxies(self, proxies: list[Proxy]) -> None:
        with self._lock:
            self._proxies = list(proxies)
            self._valid = [p for p in proxies if p.status == "valid"]
            self._index = 0
            self._consecutive_success = 0
            self._last_switch_time = time.monotonic()

    def set_mode(self, mode: RotationMode, **params) -> None:
        with self._lock:
            self._mode = mode
            self._params = params
            self._index = 0
            self._consecutive_success = 0
            self._last_switch_time = time.monotonic()
            _logger.info("Rotator set_mode: %s, params=%s", mode, params)

            if mode == RotationMode.FIXED and self._valid:
                best = min(self._valid, key=lambda p: p.latency)
                self._index = self._valid.index(best)

    def get_current(self) -> Proxy | None:
        with self._lock:
            if not self._valid:
                return None
            return self._valid[self._index % len(self._valid)]

    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def on_request_start(self) -> ProxyEndpoint | None:
        with self._lock:
            if not self._valid:
                return None

            # BY_TIME: switch if interval has elapsed
            if self._mode == RotationMode.BY_TIME:
                interval_secs = self._params.get("interval_minutes", 5) * 60
                if time.monotonic() - self._last_switch_time >= interval_secs:
                    self._index = (self._index + 1) % len(self._valid)
                    self._last_switch_time = time.monotonic()

            proxy = self._valid[self._index % len(self._valid)]

            # ROUND_ROBIN: advance immediately so concurrent connections that
            # start before any prior one finishes still fan out across
            # distinct proxies instead of collapsing onto the same index.
            if self._mode == RotationMode.ROUND_ROBIN:
                self._index = (self._index + 1) % len(self._valid)

            return ProxyEndpoint(
                proxy_id=proxy.id,
                url=proxy.url,
                supports_rdns=proxy.supports_rdns,
            )

    async def on_request_done(self, proxy_id: int, success: bool) -> Proxy | None:
        """Returns the new current proxy if a switch happened, else None.

        Resolving the new proxy here (under the same lock acquisition that
        performs the switch) avoids a TOCTOU window a separate get_current()
        call would have against a concurrent load_proxies().
        """
        with self._lock:
            if not self._valid:
                return None

            switched = False

            # ROUND_ROBIN: rotation already happened in on_request_start
            # (each connection fans out to the next proxy immediately);
            # nothing left to do here for either outcome.

            if self._mode == RotationMode.FAILOVER:
                if not success:
                    self._index = (self._index + 1) % len(self._valid)
                    self._consecutive_success = 0
                    switched = True

            elif self._mode == RotationMode.BY_COUNT:
                threshold = self._params.get("threshold", 10)
                if success:
                    self._consecutive_success += 1
                    _logger.debug("BY_COUNT: success %d/%d", self._consecutive_success, threshold)
                    if self._consecutive_success >= threshold:
                        old_idx = self._index
                        self._index = (self._index + 1) % len(self._valid)
                        self._consecutive_success = 0
                        switched = True
                        _logger.info("BY_COUNT: switched proxy %d -> %d", old_idx, self._index)
                else:
                    # On failure, switch immediately
                    self._index = (self._index + 1) % len(self._valid)
                    self._consecutive_success = 0
                    switched = True
                    _logger.debug("BY_COUNT: failed, switch and reset count")

            elif self._mode == RotationMode.BY_SCENE:
                if not success:
                    self._index = (self._index + 1) % len(self._valid)
                    switched = True

            if switched:
                return self._valid[self._index % len(self._valid)]
            return None

    async def on_response_body(self, proxy_id: int, body: bytes) -> None:
        """BY_KEYWORD: switch when trigger_word appears or required_word is absent."""
        with self._lock:
            if self._mode != RotationMode.BY_KEYWORD or not self._valid:
                return

            trigger_word: str = self._params.get("trigger_word", "")
            required_word: str = self._params.get("required_word", "")

            should_switch = False
            if trigger_word and trigger_word.encode() in body:
                should_switch = True
            if required_word and required_word.encode() not in body:
                should_switch = True

            if should_switch:
                self._index = (self._index + 1) % len(self._valid)

    async def force_switch(self) -> None:
        with self._lock:
            if self._valid:
                self._index = (self._index + 1) % len(self._valid)
                self._consecutive_success = 0
