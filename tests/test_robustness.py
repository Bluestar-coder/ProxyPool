"""鲁棒性测试 - 极值、空数据、畸形输入、插件错误不崩溃"""
from __future__ import annotations

import asyncio
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.crawlers import discover_crawlers
from app.core.http_proxy import _BAD_GATEWAY, _SERVICE_UNAVAILABLE, _handle
from app.core.rotator import _quality_key
from app.db.database import Database
from app.db.models import Proxy
from app.ui.dialogs.export_proxy import _to_clash_yaml, _to_surge_conf


# ── 工具 ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    db = Database(tmp_path / "robust.db")
    db.initialize()
    yield db
    db.close()


def _insert(db: Database, host: str, status: str = "valid", region: str = "CN") -> None:
    db._conn.execute(
        "INSERT INTO proxies (host,port,type,status,region,use_count,fail_count)"
        " VALUES (?,1080,'socks5',?,?,0,0)",
        (host, status, region),
    )
    db._conn.commit()


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


# ── _quality_key 极值 ─────────────────────────────────────────────────────────


class TestQualityKeyEdgeCases:
    def test_negative_latency_treated_as_infinity(self):
        """Proxy with latency=-1 (untested) should sort after any measured latency."""
        measured = Proxy(latency=9999.0, use_count=0, fail_count=0, speed=-1.0)
        untested = Proxy(latency=-1.0,   use_count=0, fail_count=0, speed=-1.0)
        assert _quality_key(measured) < _quality_key(untested)

    def test_negative_speed_treated_as_minus_infinity(self):
        """Proxy with speed=-1 (untested) should sort after any measured speed."""
        fast = Proxy(latency=100.0, speed=500.0, use_count=0, fail_count=0)
        slow = Proxy(latency=100.0, speed=-1.0,  use_count=0, fail_count=0)
        assert _quality_key(fast) < _quality_key(slow)

    def test_zero_total_count_is_neutral(self):
        """Untested proxy (0/0) gets -0.5 success_rank - between perfect and zero."""
        perfect  = Proxy(latency=100.0, use_count=10, fail_count=0, speed=-1.0)
        untested = Proxy(latency=100.0, use_count=0,  fail_count=0, speed=-1.0)
        zero     = Proxy(latency=100.0, use_count=0,  fail_count=10, speed=-1.0)
        assert _quality_key(perfect) < _quality_key(untested) < _quality_key(zero)

    def test_100_percent_success_rate_is_best(self):
        p = Proxy(latency=100.0, use_count=100, fail_count=0, speed=-1.0)
        key = _quality_key(p)
        assert key[0] == -1.0

    def test_0_percent_success_rate_is_worst(self):
        p = Proxy(latency=100.0, use_count=0, fail_count=100, speed=-1.0)
        key = _quality_key(p)
        assert key[0] == 0.0


# ── 空 DB / 空集合 ────────────────────────────────────────────────────────────


class TestEmptyDatabase:
    def test_get_all_proxies_empty_db(self, tmp_db):
        assert tmp_db.get_all_proxies() == []

    def test_count_proxies_empty_db(self, tmp_db):
        assert tmp_db.count_proxies() == 0
        assert tmp_db.count_proxies(status="valid") == 0

    def test_distinct_regions_empty_db(self, tmp_db):
        assert tmp_db.get_distinct_regions() == []

    def test_get_all_with_nonexistent_region(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        assert tmp_db.get_all_proxies(region="XX") == []

    def test_count_with_nonexistent_region(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        assert tmp_db.count_proxies(region="XX") == 0

    def test_pagination_beyond_rows_returns_empty(self, tmp_db):
        for i in range(5):
            _insert(tmp_db, f"1.1.1.{i}")
        result = tmp_db.get_all_proxies(page=10, page_size=5)
        assert result == []


# ── 导出格式极值 ──────────────────────────────────────────────────────────────


class TestExportEdgeCases:
    def test_empty_proxy_list_clash(self):
        out = _to_clash_yaml([], redact=True)
        assert out.startswith("proxies:")
        assert "server:" not in out

    def test_empty_proxy_list_surge(self):
        out = _to_surge_conf([], redact=True)
        assert out.startswith("[Proxy]")
        assert "socks5" not in out

    def test_proxy_no_username_clash_no_auth_block(self):
        p = Proxy(host="1.2.3.4", port=1080, username="", password="", region="CN")
        out = _to_clash_yaml([p], redact=False)
        assert "username" not in out
        assert "password" not in out

    def test_proxy_no_username_surge_no_auth_inline(self):
        p = Proxy(host="1.2.3.4", port=1080, username="", password="", region="CN")
        out = _to_surge_conf([p], redact=False)
        # Should be: "name = socks5, host, port" (3 parts, no auth)
        line = [l for l in out.splitlines() if "socks5" in l][0]
        parts = [p.strip() for p in line.split(",")]
        assert len(parts) == 3

    def test_proxy_no_region_clash_name_has_no_dash_region(self):
        p = Proxy(host="1.2.3.4", port=1080, region="")
        out = _to_clash_yaml([p], redact=True)
        # Name should be "SOCKS5-1.2.3.4:1080", not "SOCKS5--1.2.3.4:1080"
        assert "--" not in out

    def test_unicode_in_username_does_not_crash(self):
        p = Proxy(host="1.2.3.4", port=1080, username="用户", password="密码", region="CN")
        out_clash = _to_clash_yaml([p], redact=False)
        out_surge = _to_surge_conf([p], redact=False)
        assert "用户" in out_clash
        assert "用户" in out_surge


# ── HTTP 代理鲁棒性 ───────────────────────────────────────────────────────────


class TestHttpProxyRobustness:
    def _ep_rot(self):
        ep = MagicMock(proxy_id=1, url="socks5://127.0.0.1:1080", supports_rdns=True)
        r = MagicMock()
        r.on_request_start = AsyncMock(return_value=ep)
        r.on_request_done = AsyncMock()
        return r

    def _no_rot(self):
        r = MagicMock()
        r.on_request_start = AsyncMock(return_value=None)
        return r

    @pytest.mark.asyncio
    async def test_connect_missing_port_returns_502(self):
        """CONNECT host.example HTTP/1.1 (no port) -> int(host) ValueError -> 502."""
        rot = self._ep_rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=OSError())
            await _handle(
                _reader(b"CONNECT host.example HTTP/1.1\r\nHost: host\r\n\r\n"),
                w, rot,
            )
        # ValueError on int("host.example") -> _BAD_GATEWAY or upstream failure
        assert _BAD_GATEWAY in bytes(w.data) or w.closed

    @pytest.mark.asyncio
    async def test_connect_port_zero_handled(self):
        """CONNECT host:0 should fail at SOCKS5 level, not locally."""
        rot = self._ep_rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=OSError("invalid port"))
            await _handle(
                _reader(b"CONNECT host.example:0 HTTP/1.1\r\nHost: host\r\n\r\n"),
                w, rot,
            )
        assert _BAD_GATEWAY in bytes(w.data)

    @pytest.mark.asyncio
    async def test_empty_request_line_closes_writer(self):
        """Empty first line (EOF immediately) -> writer closed."""
        rot = self._no_rot()
        w = _Writer()
        await _handle(_reader(b"\r\n"), w, rot)
        assert w.closed

    @pytest.mark.asyncio
    async def test_single_word_request_closes_writer(self):
        """Only 1 part in request line -> parts != 3 -> close."""
        rot = self._no_rot()
        w = _Writer()
        await _handle(_reader(b"CONNECT\r\n"), w, rot)
        assert w.closed

    @pytest.mark.asyncio
    async def test_two_part_request_closes_writer(self):
        """2-part request line (missing HTTP version) -> close."""
        rot = self._no_rot()
        w = _Writer()
        await _handle(_reader(b"CONNECT host:443\r\n"), w, rot)
        assert w.closed

    @pytest.mark.asyncio
    async def test_no_upstream_always_returns_503(self):
        """Regardless of request type, no upstream proxy -> 503."""
        rot = self._no_rot()
        for request in [
            b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",
            b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n",
        ]:
            w = _Writer()
            await _handle(_reader(request), w, rot)
            assert _SERVICE_UNAVAILABLE in bytes(w.data), f"no 503 for {request[:30]}"


# ── 爬虫发现鲁棒性 ────────────────────────────────────────────────────────────


class TestCrawlerDiscoveryRobustness:
    def test_empty_plugin_dir_returns_builtins(self, tmp_path):
        classes = discover_crawlers(plugin_dir=tmp_path)
        names = {c.__name__ for c in classes}
        assert "FofaCrawler" in names

    def test_plugin_dir_with_non_py_files_ignored(self, tmp_path):
        (tmp_path / "readme.txt").write_text("not a plugin")
        (tmp_path / "data.json").write_text("{}")
        classes = discover_crawlers(plugin_dir=tmp_path)
        names = {c.__name__ for c in classes}
        assert "FofaCrawler" in names

    def test_plugin_with_syntax_error_is_skipped_gracefully(self, tmp_path):
        """Broken plugin must not prevent good plugins from loading."""
        (tmp_path / "bad_plugin.py").write_text("class Invalid(\n")  # syntax error
        (tmp_path / "good_plugin.py").write_text(textwrap.dedent("""\
            from app.core.crawlers.base import BaseCrawler, CrawlPage
            class RobustCrawler(BaseCrawler):
                source = "robust"
                async def fetch_page(self, session, query, cursor):
                    return CrawlPage(items=[], next_cursor=None)
        """))
        classes = discover_crawlers(plugin_dir=tmp_path)
        names = {c.__name__ for c in classes}
        assert "RobustCrawler" in names, "Good plugin was not loaded"

    def test_plugin_with_import_error_is_skipped(self, tmp_path):
        """Plugin importing non-existent module must not crash discover_crawlers."""
        (tmp_path / "bad_import.py").write_text(
            "from nonexistent_module_xyz import something\n"
        )
        classes = discover_crawlers(plugin_dir=tmp_path)
        names = {c.__name__ for c in classes}
        assert "FofaCrawler" in names

    def test_none_plugin_dir_returns_builtins(self):
        classes = discover_crawlers(plugin_dir=None)
        assert len(classes) >= 4

    def test_no_abstract_base_classes_in_result(self):
        """BaseCrawler itself should not appear in the result."""
        from app.core.crawlers.base import BaseCrawler
        classes = discover_crawlers()
        assert BaseCrawler not in classes


# ── Proxy dataclass 鲁棒性 ───────────────────────────────────────────────────


class TestProxyDataclass:
    def test_url_without_auth(self):
        p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="", password="")
        assert p.url == "socks5://1.2.3.4:1080"

    def test_url_with_auth(self):
        p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="p")
        assert p.url == "socks5://u:p@1.2.3.4:1080"

    def test_redacted_url_masks_password(self):
        p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="secret")
        assert "secret" not in p.redacted_url
        assert "***" in p.redacted_url

    def test_default_values_are_safe(self):
        p = Proxy()
        assert p.host == ""
        assert p.port == 0
        assert p.use_count == 0
        assert p.fail_count == 0
        assert p.status == "unknown"
