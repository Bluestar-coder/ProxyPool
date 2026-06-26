from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import platformdirs
from app.db.database import Database

DATA_DIR = Path(platformdirs.user_data_dir("ProxyPool", appauthor=False))
DB_PATH = DATA_DIR / "proxies.db"

_DEFAULTS: dict = {
    "listen_port": 51024,
    "rotation_mode": "round_robin",
    "rotation_params": {},
    "validator_concurrency": 100,
    "validator_timeout": 10,
    "validator_endpoint": "https://httpbin.org/ip",
    "validator_endpoint_backup": "https://ip-api.com/json",
    "geo_cache_ttl": 86400,
    "page_size": 10,
    "export_redact_password": True,
}


@dataclass
class Config:
    _db: Database = field(repr=False)

    listen_port: int = 51024
    rotation_mode: str = "round_robin"
    rotation_params: dict = field(default_factory=dict)
    validator_concurrency: int = 100
    validator_timeout: int = 10
    validator_endpoint: str = "https://httpbin.org/ip"
    validator_endpoint_backup: str = "https://ip-api.com/json"
    geo_cache_ttl: int = 86400
    page_size: int = 10
    export_redact_password: bool = True

    @classmethod
    def load(cls, db: Database) -> "Config":
        c = cls(_db=db)
        for key, default in _DEFAULTS.items():
            setattr(c, key, db.get_config(key, default))
        return c

    def save(self):
        for key in _DEFAULTS:
            self._db.set_config(key, getattr(self, key))
