import pytest
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


def test_reset_proxy_status(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    pid = db.get_all_proxies()[0].id
    db.update_validation(ValidationResult(proxy_id=pid, success=True, latency=50.0, anonymity="", region=""))
    assert db.get_proxy(pid).status == "valid"
    db.reset_proxy_status([pid])
    assert db.get_proxy(pid).status == "unknown"


def test_keyring_password_round_trip(db, monkeypatch):
    """Password stored in keyring, not SQLite; get_all_proxies restores it."""
    store: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda svc, key, pwd: store.update({key: pwd}))
    monkeypatch.setattr("keyring.get_password", lambda svc, key: store.get(key))

    p = Proxy(host="2.3.4.5", port=1080, type="socks5", username="user", password="s3cr3t", source="manual")
    db.upsert_proxy(p)

    raw = db._conn.execute("SELECT password FROM proxies WHERE host='2.3.4.5'").fetchone()
    assert raw["password"] == "", "plaintext password must not be stored in SQLite"

    proxies = db.get_all_proxies()
    assert proxies[0].password == "s3cr3t"


def test_keyring_migration(db, monkeypatch):
    """Existing plaintext passwords are migrated to keyring by _migrate_passwords_to_keyring."""
    store: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda svc, key, pwd: store.update({key: pwd}))
    monkeypatch.setattr("keyring.get_password", lambda svc, key: store.get(key))

    db._conn.execute(
        "INSERT INTO proxies(host, port, type, username, password, source) VALUES(?,?,?,?,?,?)",
        ("3.4.5.6", 1080, "socks5", "admin", "oldpass", "manual"),
    )
    db._conn.commit()

    db._migrate_passwords_to_keyring()

    raw = db._conn.execute("SELECT password FROM proxies WHERE host='3.4.5.6'").fetchone()
    assert raw["password"] == "", "SQLite column must be cleared after migration"
    assert "oldpass" in store.values(), "password must be in keyring after migration"


def test_auto_crawl_config_round_trip_keeps_api_key_out_of_sqlite(db, monkeypatch):
    """FOFA api_key must go through keyring, never land in app_config as plaintext."""
    store: dict[str, str] = {}
    monkeypatch.setattr("keyring.set_password", lambda svc, key, pwd: store.update({key: pwd}))
    monkeypatch.setattr("keyring.get_password", lambda svc, key: store.get(key))

    config = {
        "fofa": {"enabled": True, "limit": 500, "api_key": "user@example.com:s3cr3tkey", "queries": ["port=1080"]},
        "free": {"enabled": True, "limit": 50},
    }
    db.save_auto_crawl_config(config)

    raw = db._conn.execute("SELECT value FROM app_config WHERE key='auto_crawl_config'").fetchone()
    assert "s3cr3tkey" not in raw["value"], "api_key must not be stored in app_config"
    assert "user@example.com:s3cr3tkey" in store.values(), "api_key must be in keyring"

    loaded = db.load_auto_crawl_config()
    assert loaded == config


def test_auto_crawl_config_returns_none_when_never_saved(db):
    assert db.load_auto_crawl_config() is None


def test_get_distinct_regions(db):
    for host, region in [("1.1.1.1", "CN"), ("2.2.2.2", "US"), ("3.3.3.3", "CN"), ("4.4.4.4", "")]:
        p = Proxy(host=host, port=1080, type="socks5", region=region, source="manual")
        db.upsert_proxy(p)
    regions = db.get_distinct_regions()
    assert regions == ["CN", "US"]   # sorted, empty excluded


def test_get_all_proxies_filters_by_region(db):
    for host, region in [("1.1.1.1", "CN"), ("2.2.2.2", "US"), ("3.3.3.3", "CN")]:
        db.upsert_proxy(Proxy(host=host, port=1080, type="socks5", region=region, source="manual"))
    cn = db.get_all_proxies(region="CN")
    assert len(cn) == 2
    assert all(p.region == "CN" for p in cn)


def test_count_proxies_filters_by_region(db):
    for host, region in [("1.1.1.1", "CN"), ("2.2.2.2", "US")]:
        db.upsert_proxy(Proxy(host=host, port=1080, type="socks5", region=region, source="manual"))
    assert db.count_proxies(region="CN") == 1
    assert db.count_proxies(region="US") == 1
    assert db.count_proxies() == 2
