import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.http_proxy import _BAD_GATEWAY, _SERVICE_UNAVAILABLE, _handle


def _make_reader(data: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    r.feed_eof()
    return r


class _FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def get_extra_info(self, key, default=None):
        return ("127.0.0.1", 12345) if key == "peername" else default


def _make_rotator(endpoint=None):
    r = MagicMock()
    ep = endpoint or MagicMock(proxy_id=1, url="socks5://127.0.0.1:1080", supports_rdns=True)
    r.on_request_start = AsyncMock(return_value=ep)
    r.on_request_done = AsyncMock(return_value=None)
    r.on_response_body = AsyncMock(return_value=None)
    return r, ep


@pytest.mark.asyncio
async def test_handle_returns_503_when_no_proxy():
    rotator, _ = _make_rotator()
    rotator.on_request_start = AsyncMock(return_value=None)
    reader = _make_reader(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    writer = _FakeWriter()
    await _handle(reader, writer, rotator)
    assert _SERVICE_UNAVAILABLE in bytes(writer.data)
    assert writer.closed


@pytest.mark.asyncio
async def test_handle_returns_502_on_socks_failure():
    rotator, _ = _make_rotator()
    reader = _make_reader(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com\r\n\r\n")
    writer = _FakeWriter()
    with patch("app.core.http_proxy.Socks5Proxy.from_url") as mock_proxy_cls:
        mock_proxy = MagicMock()
        mock_proxy.connect = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        mock_proxy_cls.return_value = mock_proxy
        await _handle(reader, writer, rotator)
    assert _BAD_GATEWAY in bytes(writer.data)
    rotator.on_request_done.assert_awaited_once_with(1, success=False)


@pytest.mark.asyncio
async def test_handle_malformed_request_closes_writer():
    rotator, _ = _make_rotator()
    reader = _make_reader(b"GARBAGE\r\n")
    writer = _FakeWriter()
    await _handle(reader, writer, rotator)
    assert writer.closed


@pytest.mark.asyncio
async def test_handle_http_502_on_socks_failure():
    rotator, _ = _make_rotator()
    reader = _make_reader(b"GET http://example.com/path HTTP/1.1\r\nHost: example.com\r\n\r\n")
    writer = _FakeWriter()
    with patch("app.core.http_proxy.Socks5Proxy.from_url") as mock_proxy_cls:
        mock_proxy = MagicMock()
        mock_proxy.connect = AsyncMock(side_effect=OSError("refused"))
        mock_proxy_cls.return_value = mock_proxy
        await _handle(reader, writer, rotator)
    assert _BAD_GATEWAY in bytes(writer.data)
    rotator.on_request_done.assert_awaited_once_with(1, success=False)
