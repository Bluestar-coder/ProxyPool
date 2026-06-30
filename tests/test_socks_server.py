import asyncio
import struct
import socket
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.socks_server import build_socks5_reply, parse_address, safe_proxy_addr


@pytest.mark.asyncio
async def test_parse_ipv4():
    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        bytes([1]),                    # atyp
        socket.inet_aton("1.2.3.4"),  # IP
        struct.pack("!H", 8080),       # port
    ])
    host, port = await parse_address(1, reader)
    assert host == "1.2.3.4"
    assert port == 8080


@pytest.mark.asyncio
async def test_parse_domain():
    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        bytes([3]),          # atyp
        bytes([11]),         # domain length
        b"example.com",
        struct.pack("!H", 443),
    ])
    host, port = await parse_address(3, reader)
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
