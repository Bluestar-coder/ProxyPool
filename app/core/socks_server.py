from __future__ import annotations

import asyncio
import socket
import struct

from PyQt6.QtCore import pyqtSignal
from python_socks.async_.asyncio import Proxy

from app.core.rotator import ProxyRotator
from app.core.worker_thread import AsyncWorkerThread


def build_socks5_reply(code: int) -> bytes:
    return bytes([5, code, 0, 1, 0, 0, 0, 0, 0, 0])


def safe_proxy_addr(url: str) -> str:
    """host:port for display/logging - strips scheme and any credentials."""
    after_scheme = url.split("://", 1)[-1]
    return after_scheme.rsplit("@", 1)[-1].rstrip("/")



async def _relay(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(4096)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, asyncio.IncompleteReadError, BrokenPipeError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


class SocksServerThread(AsyncWorkerThread):
    status_changed = pyqtSignal(str)   # "running" | "stopped" | "no_upstream"
    client_connected = pyqtSignal(str)  # "proxy -> target"
    proxy_switched = pyqtSignal(str)    # "host:port" of new proxy

    def __init__(self, rotator: ProxyRotator, port: int = 51024) -> None:  # pragma: no cover
        super().__init__()
        self._rotator = rotator
        self._port = port
        self._last_shown_proxy_id: int | None = None

    async def main(self) -> None:  # pragma: no cover
        server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", self._port
        )
        self.status_changed.emit("running")
        async with server:
            await server.serve_forever()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._do_socks5(reader, writer)
        except Exception:
            try:
                writer.close()
            except Exception:
                pass

    async def _do_socks5(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        _T = 30.0  # per-read handshake timeout; slow clients are dropped
        # Greeting
        header = await asyncio.wait_for(reader.readexactly(2), timeout=_T)
        if header[0] != 5:
            writer.close()
            return
        nmethods = header[1]
        methods = await asyncio.wait_for(reader.readexactly(nmethods), timeout=_T)
        if 0 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            writer.close()
            return
        writer.write(b"\x05\x00")
        await writer.drain()

        # Request
        req_header = await asyncio.wait_for(reader.readexactly(4), timeout=_T)
        ver, cmd, _rsv, atyp = req_header

        if cmd != 1:
            writer.write(build_socks5_reply(0x07))
            await writer.drain()
            writer.close()
            return

        if atyp == 4:
            writer.write(build_socks5_reply(0x08))
            await writer.drain()
            writer.close()
            return

        host, port = await asyncio.wait_for(_parse_address_with_hint(atyp, reader), timeout=_T)

        endpoint = await self._rotator.on_request_start()
        if endpoint is None:
            self.status_changed.emit("no_upstream")
            writer.write(build_socks5_reply(0x04))
            await writer.drain()
            writer.close()
            return

        proxy_addr = safe_proxy_addr(endpoint.url)
        self.client_connected.emit(f"{proxy_addr} -> {host}:{port}")

        # Some modes (e.g. ROUND_ROBIN) decide the next proxy inside
        # on_request_start rather than on_request_done; catch those switches
        # here so the "current proxy" UI label stays accurate in real time.
        if endpoint.proxy_id != self._last_shown_proxy_id:
            self._last_shown_proxy_id = endpoint.proxy_id
            self.proxy_switched.emit(proxy_addr)

        try:
            proxy = Proxy.from_url(endpoint.url, rdns=endpoint.supports_rdns)
            sock = await asyncio.wait_for(
                proxy.connect(dest_host=host, dest_port=port), timeout=8
            )
        except Exception:
            cur = await self._rotator.on_request_done(endpoint.proxy_id, success=False)
            if cur:
                self._last_shown_proxy_id = cur.id
                self.proxy_switched.emit(f"{cur.host}:{cur.port}")
            writer.write(build_socks5_reply(0x05))
            await writer.drain()
            writer.close()
            return

        rem_reader, rem_writer = await asyncio.open_connection(sock=sock)

        try:
            writer.write(build_socks5_reply(0x00))
            await writer.drain()
        except Exception:
            try:
                rem_writer.close()
            except Exception:
                pass
            cur = await self._rotator.on_request_done(endpoint.proxy_id, success=False)
            if cur:
                self._last_shown_proxy_id = cur.id
                self.proxy_switched.emit(f"{cur.host}:{cur.port}")
            try:
                writer.close()
            except Exception:
                pass
            return

        await asyncio.gather(
            _relay(reader, rem_writer),
            _relay(rem_reader, writer),
            return_exceptions=True,
        )

        cur = await self._rotator.on_request_done(endpoint.proxy_id, success=True)
        if cur:
            self._last_shown_proxy_id = cur.id
            self.proxy_switched.emit(f"{cur.host}:{cur.port}")
        try:
            writer.close()
        except Exception:
            pass


async def _parse_address_with_hint(
    atyp: int, reader: asyncio.StreamReader
) -> tuple[str, int]:
    """Production path: atyp already read from req_header; parse remaining bytes."""
    if atyp == 1:
        ip_bytes = await reader.readexactly(4)
        host = socket.inet_ntoa(ip_bytes)
    elif atyp == 3:
        length_byte = await reader.readexactly(1)
        length = length_byte[0]
        domain_bytes = await reader.readexactly(length)
        host = domain_bytes.decode()
    elif atyp == 4:
        raise ValueError("ipv6_unsupported")
    else:
        raise ValueError(f"unknown_atyp_{atyp}")

    port_bytes = await reader.readexactly(2)
    port = struct.unpack("!H", port_bytes)[0]
    return host, port
