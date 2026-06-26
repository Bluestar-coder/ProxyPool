import pytest
from pathlib import Path
from app.db.database import Database
from app.db.models import Proxy, ValidationResult


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    yield d
    d.close()


def test_upsert_and_get_proxy(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", source="manual")
    db.upsert_proxy(p)
    rows = db.get_all_proxies()
    assert len(rows) == 1
    assert rows[0].host == "1.2.3.4"
    assert rows[0].id > 0


def test_upsert_deduplicates(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    db.upsert_proxy(p)
    assert len(db.get_all_proxies()) == 1


def test_upsert_preserves_use_count(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    stored = db.get_all_proxies()[0]
    stored.use_count = 5
    db.upsert_proxy(stored)
    assert db.get_all_proxies()[0].use_count == 5


def test_delete_proxy(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    pid = db.get_all_proxies()[0].id
    db.delete_proxy(pid)
    assert db.get_all_proxies() == []


def test_update_validation(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    pid = db.get_all_proxies()[0].id
    result = ValidationResult(proxy_id=pid, success=True, latency=120.5,
                              anonymity="high", region="CN-广东")
    db.update_validation(result)
    updated = db.get_proxy(pid)
    assert updated.status == "valid"
    assert updated.latency == 120.5


def test_config_get_set(db):
    db.set_config("listen_port", 51024)
    assert db.get_config("listen_port", 0) == 51024


def test_config_default(db):
    assert db.get_config("missing_key", "default") == "default"
