"""安全性测试 - 密码脱敏、SQL 注入防护、异常输入处理"""
from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.http_proxy import _BAD_GATEWAY, _SERVICE_UNAVAILABLE, _handle
from app.db.database import Database
from app.db.models import Proxy
from app.ui.dialogs.export_proxy import _to_clash_yaml, _to_surge_conf


# ── 工具 ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    db = Database(tmp_path / "sec.db")
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


def _proxy_with_pwd(password: str = "verysecret") -> Proxy:
    return Proxy(host="1.2.3.4", port=1080, username="alice", password=password, region="CN")


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


# ── 密码脱敏 ─────────────────────────────────────────────────────────────────


class TestPasswordRedaction:
    def test_clash_redact_hides_password(self):
        out = _to_clash_yaml([_proxy_with_pwd("verysecret")], redact=True)
        assert "verysecret" not in out
        assert "***" in out

    def test_clash_plain_reveals_password(self):
        out = _to_clash_yaml([_proxy_with_pwd("verysecret")], redact=False)
        assert "verysecret" in out

    def test_surge_redact_hides_password(self):
        out = _to_surge_conf([_proxy_with_pwd("verysecret")], redact=True)
        assert "verysecret" not in out
        assert "***" in out

    def test_surge_plain_reveals_password(self):
        out = _to_surge_conf([_proxy_with_pwd("verysecret")], redact=False)
        assert "verysecret" in out

    def test_clash_redacted_contains_no_full_auth_url(self):
        out = _to_clash_yaml([_proxy_with_pwd("s3cr3t")], redact=True)
        assert re.search(r"socks5://[^:]+:s3cr3t@", out) is None

    def test_surge_redacted_contains_no_plain_password(self):
        out = _to_surge_conf([_proxy_with_pwd("s3cr3t")], redact=True)
        assert "s3cr3t" not in out

    def test_multiple_proxies_none_leak_in_redacted_clash(self):
        proxies = [_proxy_with_pwd(f"pwd_{i}") for i in range(10)]
        out = _to_clash_yaml(proxies, redact=True)
        for i in range(10):
            assert f"pwd_{i}" not in out, f"password pwd_{i} leaked"

    def test_multiple_proxies_none_leak_in_redacted_surge(self):
        proxies = [_proxy_with_pwd(f"pwd_{i}") for i in range(10)]
        out = _to_surge_conf(proxies, redact=True)
        for i in range(10):
            assert f"pwd_{i}" not in out, f"password pwd_{i} leaked"

    def test_proxy_without_username_produces_no_password_field(self):
        p = Proxy(host="1.2.3.4", port=1080, username="", password="hidden")
        clash = _to_clash_yaml([p], redact=False)
        surge = _to_surge_conf([p], redact=False)
        # username="" means no auth block should be emitted
        assert "hidden" not in clash
        assert "hidden" not in surge


# ── SQL 注入防护 ──────────────────────────────────────────────────────────────


_SQL_PAYLOADS = [
    "'; DROP TABLE proxies;--",
    "' OR '1'='1",
    "CN' UNION SELECT * FROM proxies--",
    "'; SELECT * FROM sqlite_master;--",
    "valid' OR 1=1--",
    "\x00NULL",
    "CN\nOR 1=1",
]


class TestSqlInjection:
    def test_region_injection_returns_empty_not_all_rows(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        for payload in _SQL_PAYLOADS:
            result = tmp_db.get_all_proxies(region=payload)
            assert result == [], f"payload {payload!r} leaked {len(result)} row(s)"

    def test_status_injection_returns_empty_not_all_rows(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", status="valid")
        for payload in _SQL_PAYLOADS:
            result = tmp_db.get_all_proxies(status=payload)
            assert result == [], f"payload {payload!r} leaked {len(result)} row(s)"

    def test_count_injection_returns_zero(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        for payload in _SQL_PAYLOADS:
            count = tmp_db.count_proxies(region=payload)
            assert count == 0, f"payload {payload!r} returned count={count}"

    def test_table_survives_drop_injection(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", region="CN")
        try:
            tmp_db.get_all_proxies(region="'; DROP TABLE proxies;--")
        except Exception:
            pass
        # Table must still be queryable
        result = tmp_db.get_all_proxies(region="CN")
        assert len(result) == 1, "proxies table was dropped or data lost"

    def test_combined_status_region_injection(self, tmp_db):
        _insert(tmp_db, "1.1.1.1", status="valid", region="CN")
        for payload in _SQL_PAYLOADS:
            result = tmp_db.get_all_proxies(status=payload, region=payload)
            assert result == []


# ── HTTP 代理安全 ─────────────────────────────────────────────────────────────


class TestHttpProxySecurity:
    def _failing_rot(self):
        ep = MagicMock(proxy_id=1, url="socks5://127.0.0.1:1080", supports_rdns=True)
        r = MagicMock()
        r.on_request_start = AsyncMock(return_value=ep)
        r.on_request_done = AsyncMock()
        return r

    def _no_upstream_rot(self):
        r = MagicMock()
        r.on_request_start = AsyncMock(return_value=None)
        return r

    @pytest.mark.asyncio
    async def test_path_traversal_host_in_connect_does_not_crash(self):
        """Path-traversal-like CONNECT target must fail at SOCKS5, not locally."""
        rot = self._failing_rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=ConnectionRefusedError())
            await _handle(_reader(b"CONNECT ../../../etc:80 HTTP/1.1\r\n\r\n"), w, rot)
        assert _BAD_GATEWAY in bytes(w.data)

    @pytest.mark.asyncio
    async def test_oversized_hostname_handled_gracefully(self):
        """8 KiB hostname in CONNECT must not crash; proxy returns error response."""
        long_host = "a" * 8192
        rot = self._failing_rot()
        w = _Writer()
        with patch("app.core.http_proxy.Socks5Proxy.from_url") as m:
            m.return_value.connect = AsyncMock(side_effect=OSError("too long"))
            await _handle(
                _reader(f"CONNECT {long_host}:443 HTTP/1.1\r\n\r\n".encode()),
                w, rot,
            )
        assert _BAD_GATEWAY in bytes(w.data) or w.closed

    @pytest.mark.asyncio
    async def test_crlf_injection_in_connect_request_rejected(self):
        """CRLF in request line (only 2 parts on first line) -> writer closed."""
        rot = self._no_upstream_rot()
        w = _Writer()
        # readline() stops at first \r\n -> "CONNECT evil.com:443" -> 2 parts -> close
        await _handle(
            _reader(b"CONNECT evil.com:443\r\nX-Injected: bad HTTP/1.1\r\n\r\n"),
            w, rot,
        )
        assert w.closed

    @pytest.mark.asyncio
    async def test_null_bytes_do_not_crash_handler(self):
        """NULL bytes in request are handled without exception."""
        rot = self._no_upstream_rot()
        w = _Writer()
        await _handle(_reader(b"CONNECT \x00evil.com:443\x00 HTTP/1.1\r\n\r\n"), w, rot)
        # Either 503 (no upstream) or closed; must not raise
        assert _SERVICE_UNAVAILABLE in bytes(w.data) or w.closed

    @pytest.mark.asyncio
    async def test_no_upstream_never_leaks_socks5_credentials(self):
        """503 response must not contain any credential information."""
        rot = self._no_upstream_rot()
        w = _Writer()
        await _handle(_reader(b"CONNECT secret.example:443 HTTP/1.1\r\n\r\n"), w, rot)
        response = bytes(w.data).decode(errors="replace")
        assert "password" not in response.lower()
        assert "socks5://" not in response
