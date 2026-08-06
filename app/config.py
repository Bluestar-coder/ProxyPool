from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from app.db.database import Database

DATA_DIR = Path(
    os.environ.get("PROXYPOOL_DATA_DIR")
    or platformdirs.user_data_dir("ProxyPool", appauthor=False)
)
DB_PATH = Path(os.environ.get("PROXYPOOL_DB_PATH") or str(DATA_DIR / "proxies.db"))

_DEFAULTS: dict = {
    "listen_port": 51024,
    "rest_api_port": 51025,
    "http_proxy_port": 51026,
    "rotation_mode": "round_robin",
    "rotation_params": {},
    "validator_concurrency": 50,
    "validator_timeout": 15,
    "validator_endpoint": "http://ip-api.com/json",
    "validator_endpoint_backup": "https://httpbin.org/ip",
    "geo_cache_ttl": 86400,
    "page_size": 10,
    "export_redact_password": True,
    "auto_maintenance_enabled": False,
}

# Environment variables take highest priority over DB-stored user preferences.
_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "PROXYPOOL_SOCKS_PORT":              ("listen_port",             int),
    "PROXYPOOL_REST_PORT":               ("rest_api_port",           int),
    "PROXYPOOL_HTTP_PORT":               ("http_proxy_port",         int),
    "PROXYPOOL_VALIDATOR_CONCURRENCY":   ("validator_concurrency",   int),
    "PROXYPOOL_VALIDATOR_TIMEOUT":       ("validator_timeout",       int),
    "PROXYPOOL_VALIDATOR_ENDPOINT":      ("validator_endpoint",      str),
}


@dataclass
class Config:
    _db: Database = field(repr=False)

    listen_port: int = 51024
    rest_api_port: int = 51025
    http_proxy_port: int = 51026
    rotation_mode: str = "round_robin"
    rotation_params: dict = field(default_factory=dict)
    validator_concurrency: int = 50
    validator_timeout: int = 15
    validator_endpoint: str = "http://ip-api.com/json"
    validator_endpoint_backup: str = "https://httpbin.org/ip"
    geo_cache_ttl: int = 86400
    page_size: int = 10
    export_redact_password: bool = True
    auto_maintenance_enabled: bool = False

    @classmethod
    def load(cls, db: Database) -> "Config":
        c = cls(_db=db)
        for key, default in _DEFAULTS.items():
            setattr(c, key, db.get_config(key, default))
        for env_key, (attr, cast) in _ENV_OVERRIDES.items():
            if val := os.environ.get(env_key):
                try:
                    setattr(c, attr, cast(val))
                except (ValueError, TypeError) as exc:
                    logging.getLogger(__name__).warning(
                        "忽略无效环境变量 %s=%r: %s", env_key, val, exc
                    )
        return c

    def save(self):
        for key in _DEFAULTS:
            self._db.set_config(key, getattr(self, key))
