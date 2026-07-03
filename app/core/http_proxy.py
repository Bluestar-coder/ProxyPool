from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from python_socks.async_.asyncio import Proxy as Socks5Proxy
from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from app.core.rotator import ProxyRotator

_logger = logging.getLogger(__name__)
_CONNECT_ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"
_BAD_GATEWAY = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
_SERVICE_UNAVAILABLE = b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while chunk := await src.read(65536):
            dst.write(chunk)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    rotator: "ProxyRotator",
) -> None:
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
    except (asyncio.TimeoutError, ConnectionResetError):
        writer.close()
        return

    parts = request_line.decode(errors="replace").strip().split()
    if len(parts) != 3:
        writer.close()
        return

    method, target, _ = parts

    # Consume remaining request headers
    try:
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line in (b"\r\n", b"\n", b""):
                break
    except asyncio.TimeoutError:
        writer.close()
        return

    # Resolve the upstream SOCKS5 proxy
    endpoint = await rotator.on_request_start()
    if endpoint is None:
        writer.write(_SERVICE_UNAVAILABLE)
        await writer.drain()
        writer.close()
        return

    if method == "CONNECT":
        await _handle_connect(reader, writer, target, endpoint, rotator)
    else:
        # Plain HTTP: reconnect to upstream target via SOCKS5 and replay request
        await _handle_http(reader, writer, method, target, request_line, endpoint, rotator)


async def _handle_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    target: str,
    endpoint,
    rotator: "ProxyRotator",
) -> None:
    try:
        host, _, port_str = target.rpartition(":")
        port = int(port_str) if port_str else 443
    except ValueError:
        writer.write(_BAD_GATEWAY)
        await writer.drain()
        writer.close()
        return

    try:
        proxy = Socks5Proxy.from_url(endpoint.url, rdns=endpoint.supports_rdns)
        sock = await proxy.connect(dest_host=host, dest_port=port, timeout=15)
        up_reader, up_writer = await asyncio.open_connection(sock=sock, limit=2**20)
    except Exception as exc:
        _logger.debug("CONNECT %s failed via %s: %s", target, endpoint.url, exc)
        writer.write(_BAD_GATEWAY)
        await writer.drain()
        writer.close()
        await rotator.on_request_done(endpoint.proxy_id, success=False)
        return

    writer.write(_CONNECT_ESTABLISHED)
    await writer.drain()
    await rotator.on_request_done(endpoint.proxy_id, success=True)

    await asyncio.gather(
        _pipe(reader, up_writer),
        _pipe(up_reader, writer),
        return_exceptions=True,
    )


async def _handle_http(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    method: str,
    target: str,
    first_line: bytes,
    endpoint,
    rotator: "ProxyRotator",
) -> None:
    # Extract host and port from the absolute URL target
    try:
        without_scheme = target.split("://", 1)[-1]
        host_port, _, path = without_scheme.partition("/")
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = host_port, 80
        path = "/" + path if path else "/"
    except Exception:
        writer.write(_BAD_GATEWAY)
        await writer.drain()
        writer.close()
        return

    try:
        proxy = Socks5Proxy.from_url(endpoint.url, rdns=endpoint.supports_rdns)
        sock = await proxy.connect(dest_host=host, dest_port=port, timeout=15)
        up_reader, up_writer = await asyncio.open_connection(sock=sock, limit=2**20)
    except Exception as exc:
        _logger.debug("HTTP %s %s failed: %s", method, target, exc)
        writer.write(_BAD_GATEWAY)
        await writer.drain()
        writer.close()
        await rotator.on_request_done(endpoint.proxy_id, success=False)
        return

    # Rewrite request line to relative path
    new_first = f"{method} {path} HTTP/1.1\r\n".encode()
    body = await reader.read(65536)
    up_writer.write(new_first + body)
    await up_writer.drain()
    await rotator.on_request_done(endpoint.proxy_id, success=True)

    response = await up_reader.read(65536)
    writer.write(response)
    await writer.drain()
    writer.close()


class HttpProxyThread(QThread):
    """HTTP/HTTPS proxy server that tunnels traffic through the SOCKS5 pool.

    Handles CONNECT (for HTTPS) and plain HTTP by routing each request
    through the rotator, so all rotation modes and usage stats apply.
    Listens on 127.0.0.1:<port> (default 51026).
    """

    client_connected = pyqtSignal(str)

    def __init__(self, rotator: "ProxyRotator", port: int = 51026, parent=None):  # pragma: no cover
        super().__init__(parent)
        self._rotator = rotator
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self) -> None:  # pragma: no cover
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:  # pragma: no cover
        server = await asyncio.start_server(
            self._on_client, "127.0.0.1", self._port, limit=2**20
        )
        _logger.info("HTTP proxy listening on http://127.0.0.1:%d", self._port)
        async with server:
            while not self.isInterruptionRequested():
                await asyncio.sleep(0.2)

    async def _on_client(  # pragma: no cover
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername", ("?", 0))
        self.client_connected.emit(f"{peer[0]}:{peer[1]}")
        await _handle(reader, writer, self._rotator)

    def stop(self) -> None:  # pragma: no cover
        self.requestInterruption()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait(3000)
