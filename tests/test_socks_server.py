import socket
import struct
from unittest.mock import AsyncMock

import pytest

from app.core.socks_server import (
    _parse_address_with_hint,
    build_socks5_reply,
    safe_proxy_addr,
)


@pytest.mark.asyncio
async def test_parse_ipv4():
    # atyp already consumed from req_header; reader only provides IP + port
    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        socket.inet_aton("1.2.3.4"),
        struct.pack("!H", 8080),
    ])
    host, port = await _parse_address_with_hint(1, reader)
    assert host == "1.2.3.4"
    assert port == 8080


@pytest.mark.asyncio
async def test_parse_domain():
    # atyp already consumed; reader provides length + domain + port
    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        bytes([11]),
        b"example.com",
        struct.pack("!H", 443),
    ])
    host, port = await _parse_address_with_hint(3, reader)
    assert host == "example.com"
    assert port == 443


def test_build_reply_success():
    reply = build_socks5_reply(0x00)
    assert reply[0] == 5
    assert reply[1] == 0x00


def test_build_reply_failure():
    reply = build_socks5_reply(0x04)
    assert reply[1] == 0x04


def test_safe_proxy_addr_no_auth():
    assert safe_proxy_addr("socks5://1.2.3.4:1080") == "1.2.3.4:1080"


def test_safe_proxy_addr_strips_credentials():
    assert safe_proxy_addr("socks5://user:pass@1.2.3.4:1080") == "1.2.3.4:1080"
