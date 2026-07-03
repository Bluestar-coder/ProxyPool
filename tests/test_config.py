"""Tests for app.config - env var override behaviour."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.db.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d


class TestConfigEnvOverrides:
    def test_load_uses_db_defaults_when_no_env(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        for key in ("PROXYPOOL_SOCKS_PORT", "PROXYPOOL_REST_PORT", "PROXYPOOL_HTTP_PORT",
                    "PROXYPOOL_VALIDATOR_CONCURRENCY", "PROXYPOOL_VALIDATOR_TIMEOUT",
                    "PROXYPOOL_VALIDATOR_ENDPOINT"):
            monkeypatch.delenv(key, raising=False)

        from app.config import Config
        cfg = Config.load(db)

        assert cfg.listen_port == 51024
        assert cfg.rest_api_port == 51025
        assert cfg.http_proxy_port == 51026
        assert cfg.validator_concurrency == 50
        assert cfg.validator_timeout == 15

    def test_socks_port_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_SOCKS_PORT", "9999")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.listen_port == 9999

    def test_rest_port_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_REST_PORT", "8080")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.rest_api_port == 8080

    def test_http_port_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_HTTP_PORT", "7070")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.http_proxy_port == 7070

    def test_validator_concurrency_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_VALIDATOR_CONCURRENCY", "10")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.validator_concurrency == 10

    def test_validator_timeout_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_VALIDATOR_TIMEOUT", "30")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.validator_timeout == 30

    def test_validator_endpoint_env_overrides_db(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_VALIDATOR_ENDPOINT", "https://example.com/check")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.validator_endpoint == "https://example.com/check"

    def test_env_overrides_db_stored_value(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        # DB has a user-saved value; env should still win.
        db.set_config("listen_port", 12345)
        monkeypatch.setenv("PROXYPOOL_SOCKS_PORT", "9001")
        from app.config import Config
        cfg = Config.load(db)
        assert cfg.listen_port == 9001

    def test_save_does_not_raise(self, db: Database, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PROXYPOOL_SOCKS_PORT", raising=False)
        from app.config import Config
        cfg = Config.load(db)
        cfg.save()  # must not raise


class TestDataDirEnvVar:
    def test_db_path_env_var_is_respected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        custom = str(tmp_path / "custom.db")
        monkeypatch.setenv("PROXYPOOL_DB_PATH", custom)
        import importlib
        import app.config as cfg_module
        importlib.reload(cfg_module)
        assert str(cfg_module.DB_PATH) == custom

    def test_data_dir_env_var_is_respected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("PROXYPOOL_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("PROXYPOOL_DB_PATH", raising=False)
        import importlib
        import app.config as cfg_module
        importlib.reload(cfg_module)
        assert cfg_module.DATA_DIR == tmp_path
        assert cfg_module.DB_PATH == tmp_path / "proxies.db"
