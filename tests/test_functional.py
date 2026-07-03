"""功能测试 - 验证核心功能的行为正确性"""
from __future__ import annotations

import asyncio
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.crawlers import discover_crawlers
from app.core.http_proxy import (
    _BAD_GATEWAY,
    _SERVICE_UNAVAILABLE,
    _handle,
)
from app.core.rotator import _quality_key
from app.db.database import Database
from app.db.models import Proxy
from app.ui.dialogs.export_proxy import _to_clash_yaml, _to_surge_conf


# ── 共用工具 ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    db = Database(tmp_path / "func.db")
    db.initialize()
    yield db
    db.close()


def _insert(db: Database, host: str, port: int = 1080,
            status: str = "valid", region: str = "CN",
            use_count: int = 0, fail_count: int = 0) -> None:
    db._conn.execute(
        "INSERT INTO proxies (host,port,type,status,region,use_count,fail_count)"
        " VALUES (?,?,?,?,?,?,?)",
        (host, port, "socks5", status, region, use_count, fail_count),
    )
    db._conn.commit()


def _proxy(**kw) -> Proxy:
    defaults = dict(host="1.2.3.4", port=1080, username="alice",
                    password="secret", region="CN", latency=100.0, speed=200.0)
    defaults.update(kw)
    return Proxy(**defaults)


def _reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


class _Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, d: bytes): self.data += d
    async def drain(self): pass
    def close(self): self.closed = True
    def get_extra_info(self, k, d=None): return ("127.0.0.1", 9) if k == "peername" else d


# ── DB 功能 ──────────────────────────────────────────────────────────────────


class TestDbCrud:
    def test_insert_and_retrieve(self, tmp_db):
        _insert(tmp_db, "10.0.0.1", region="US")
        rows = tmp_db.get_all_proxies()
        assert len(rows) == 1
        assert rows[0].host == "10.0.0.1"
        assert rows[0].region == "US"

    def test_region_filter_returns_matching_only(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        _insert(tmp_db, "2.2.2.2", region="US")
        _insert(tmp_db, "3.3.3.3", region="CN")
        result = tmp_db.get_all_proxies(region="CN")
        assert len(result) == 2
        assert all(p.region == "CN" for p in result)

    def test_region_none_returns_all(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        _insert(tmp_db, "2.2.2.2", region="US")
        assert len(tmp_db.get_all_proxies(region=None)) == 2

    def test_status_and_region_combined(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", status="valid",   region="CN")
        _insert(tmp_db, "2.2.2.2", status="invalid", region="CN")
        _insert(tmp_db, "3.3.3.3", status="valid",   region="US")
        result = tmp_db.get_all_proxies(status="valid", region="CN")
        assert len(result) == 1
        assert result[0].host == "1.1.1.1"

    def test_nonexistent_region_returns_empty(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        assert tmp_db.get_all_proxies(region="JP") == []

    def test_count_with_region(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", status="valid", region="CN")
        _insert(tmp_db, "2.2.2.2", status="valid", region="CN")
        _insert(tmp_db, "3.3.3.3", status="valid", region="US")
        assert tmp_db.count_proxies(status="valid", region="CN") == 2
        assert tmp_db.count_proxies(status="valid", region="US") == 1
        assert tmp_db.count_proxies(status="valid") == 3

    def test_distinct_regions_sorted_and_deduped(self, tmp_db):
        for i, region in enumerate(["US", "CN", "JP", "CN"]):
            _insert(tmp_db, f"10.0.0.{i}", region=region)
        regions = tmp_db.get_distinct_regions()
        assert regions == ["CN", "JP", "US"]

    def test_distinct_regions_excludes_empty_string(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        _insert(tmp_db, "2.2.2.2", region="")
        assert "" not in tmp_db.get_distinct_regions()

    def test_pagination_no_overlap(self, tmp_db):
        for i in range(9):
            _insert(tmp_db, f"10.0.0.{i}")
        p1 = tmp_db.get_all_proxies(page=1, page_size=3)
        p2 = tmp_db.get_all_proxies(page=2, page_size=3)
        assert len(p1) == 3
        assert len(p2) == 3
        assert {p.host for p in p1}.isdisjoint({p.host for p in p2})


# ── 排序功能 ─────────────────────────────────────────────────────────────────


class TestQualityKeyFunctional:
    def test_returns_3_tuple(self):
        assert len(_quality_key(_proxy(latency=50.0, use_count=5, fail_count=1))) == 3

    def test_proven_good_beats_flaky_regardless_of_latency(self):
        good = _proxy(latency=500.0, use_count=10, fail_count=0)
        bad  = _proxy(latency=10.0,  use_count=1,  fail_count=9)
        assert _quality_key(good) < _quality_key(bad)

    def test_untested_sits_between_good_and_bad(self):
        good     = _proxy(latency=200.0, use_count=10, fail_count=0)
        untested = _proxy(latency=100.0, use_count=0,  fail_count=0)
        bad      = _proxy(latency=50.0,  use_count=1,  fail_count=9)
        keys = list(map(_quality_key, [good, untested, bad]))
        assert keys[0] < keys[1] < keys[2]

    def test_same_rate_sorted_by_latency(self):
        fast = _proxy(latency=50.0,  use_count=5, fail_count=0)
        slow = _proxy(latency=200.0, use_count=5, fail_count=0)
        assert _quality_key(fast) < _quality_key(slow)

    def test_same_rate_same_latency_sorted_by_speed_desc(self):
        faster = _proxy(latency=100.0, speed=500.0, use_count=5, fail_count=0)
        slower = _proxy(latency=100.0, speed=100.0, use_count=5, fail_count=0)
        assert _quality_key(faster) < _quality_key(slower)


# ── 导出格式功能 ──────────────────────────────────────────────────────────────


class TestExportFormats:
    def test_clash_starts_with_proxies_key(self):
        assert _to_clash_yaml([_proxy()], redact=False).startswith("proxies:")

    def test_clash_required_fields_present(self):
        out = _to_clash_yaml([_proxy()], redact=False)
        assert "type: socks5" in out
        assert "server: 1.2.3.4" in out
        assert "port: 1080" in out

    def test_clash_auth_fields_when_username_set(self):
        out = _to_clash_yaml([_proxy()], redact=False)
        assert "username: alice" in out
        assert "password: secret" in out

    def test_clash_no_auth_fields_when_no_username(self):
        out = _to_clash_yaml([_proxy(username="", password="")], redact=False)
        assert "username" not in out
        assert "password" not in out

    def test_clash_region_appears_in_proxy_name(self):
        out = _to_clash_yaml([_proxy(region="JP")], redact=False)
        assert "-JP-" in out

    def test_surge_starts_with_proxy_section(self):
        assert _to_surge_conf([_proxy()], redact=False).startswith("[Proxy]")

    def test_surge_auth_inline_format(self):
        out = _to_surge_conf([_proxy()], redact=False)
        assert "socks5" in out
        assert "1.2.3.4" in out
        assert "1080" in out
        assert "alice" in out
        assert "secret" in out

    def test_surge_no_auth_when_no_username(self):
        out = _to_surge_conf([_proxy(username="", password="")], redact=False)
        assert "alice" not in out

    def test_all_proxies_present_in_output(self):
        proxies = [_proxy(host=f"10.0.0.{i}") for i in range(5)]
        for fmt_fn in (_to_clash_yaml, _to_surge_conf):
            out = fmt_fn(proxies, redact=False)
            for i in range(5):
                assert f"10.0.0.{i}" in out, f"{fmt_fn.__name__}: host 10.0.0.{i} missing"


# ── HTTP 代理功能 ─────────────────────────────────────────────────────────────


class TestHttpProxyFunctional:
    def _rot(self, ep=None):
        r = MagicMock()
        if ep is None:
            ep = MagicMock(proxy_id=1, url="socks5://127.0.0.1:1080", supports_rdns=True)
        r.on_request_start = AsyncMock(return_value=ep)
        r.on_request_done = AsyncMock()
        return r

    @pytest.mark.asyncio
    async def test_no_proxy_returns_503(self):
        rot = MagicMock()
        rot.on_request_start = AsyncMock(return_value=None)
        w = _Writer()
        await _handle(_reader(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n"), w, rot)
        assert _SERVICE_UNAVAILABLE in bytes(w.data)

    @pytest.mark.asyncio
    async def test_connect_socks_failure_returns_502_and_tracks_stats(self):
        rot = self._rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=ConnectionRefusedError())
            await _handle(
                _reader(b"CONNECT host.example:443 HTTP/1.1\r\nHost: host\r\n\r\n"),
                w, rot,
            )
        assert _BAD_GATEWAY in bytes(w.data)
        rot.on_request_done.assert_awaited_once_with(1, success=False)

    @pytest.mark.asyncio
    async def test_http_get_socks_failure_returns_502_and_tracks_stats(self):
        rot = self._rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=OSError())
            await _handle(
                _reader(b"GET http://example.com/path HTTP/1.1\r\nHost: example.com\r\n\r\n"),
                w, rot,
            )
        assert _BAD_GATEWAY in bytes(w.data)
        rot.on_request_done.assert_awaited_once_with(1, success=False)

    @pytest.mark.asyncio
    async def test_malformed_request_closes_without_calling_upstream(self):
        rot = MagicMock()
        rot.on_request_start = AsyncMock(return_value=None)
        w = _Writer()
        await _handle(_reader(b"GARBAGE\r\n"), w, rot)
        assert w.closed
        rot.on_request_start.assert_not_called()


# ── 爬虫发现功能 ──────────────────────────────────────────────────────────────


class TestCrawlerDiscoveryFunctional:
    def test_returns_list_of_types(self):
        result = discover_crawlers()
        assert isinstance(result, list)
        assert all(isinstance(c, type) for c in result)

    def test_all_builtins_present(self):
        names = {c.__name__ for c in discover_crawlers()}
        for expected in ("FofaCrawler", "QuakeCrawler", "HunterCrawler", "FreeSitesCrawler"):
            assert expected in names, f"{expected} not found"

    def test_idempotency(self):
        assert {c.__name__ for c in discover_crawlers()} == {c.__name__ for c in discover_crawlers()}

    def test_external_plugin_loaded(self, tmp_path):
        (tmp_path / "myplugin.py").write_text(textwrap.dedent("""\
            from app.core.crawlers.base import BaseCrawler, CrawlPage
            class FuncTestCrawler(BaseCrawler):
                source = "func_test"
                async def fetch_page(self, session, query, cursor):
                    return CrawlPage(items=[], next_cursor=None)
        """))
        names = {c.__name__ for c in discover_crawlers(plugin_dir=tmp_path)}
        assert "FuncTestCrawler" in names
