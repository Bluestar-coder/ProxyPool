from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QThread, pyqtSignal
from python_socks.async_.asyncio import Proxy as Socks5Proxy

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


async def _pipe_checking_keywords(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    rotator: "ProxyRotator",
    proxy_id: int,
) -> None:
    """Stream src to dst; accumulate first 1 MB so BY_KEYWORD mode can inspect it."""
    _SCAN_LIMIT = 1 << 20  # 1 MB
    scan_buf: bytearray = bytearray()
    keyword_checked = False
    try:
        while chunk := await src.read(65536):
            dst.write(chunk)
            await dst.drain()
            if not keyword_checked:
                scan_buf += chunk
                if len(scan_buf) >= _SCAN_LIMIT:
                    await rotator.on_response_body(proxy_id, bytes(scan_buf))
                    keyword_checked = True
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        if not keyword_checked:
            try:
                await rotator.on_response_body(proxy_id, bytes(scan_buf))
            except Exception:
                pass
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

    if len(request_line) > 8192:
        writer.close()
        return

    parts = request_line.decode(errors="replace").strip().split()
    if len(parts) != 3:
        writer.close()
        return

    method, target, _ = parts

    # Collect request headers to forward upstream; parse Content-Length for body relay
    headers: list[bytes] = []
    content_length = 0
    try:
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line in (b"\r\n", b"\n", b""):
                break
            if len(headers) >= 200:
                writer.write(
                    b"HTTP/1.1 431 Request Header Fields Too Large\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
                await writer.drain()
                writer.close()
                return
            headers.append(line)
            if line.lower().startswith(b"content-length:"):
                try:
                    content_length = int(line.split(b":", 1)[1].strip())
                except ValueError:
                    pass
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
        await _handle_http(
            reader, writer, method, target,
            headers, content_length, endpoint, rotator,
        )


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
        await rotator.on_request_done(endpoint.proxy_id, success=False)
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

    try:
        writer.write(_CONNECT_ESTABLISHED)
        await writer.drain()
    except Exception:
        try:
            up_writer.close()
        except Exception:
            pass
        await rotator.on_request_done(endpoint.proxy_id, success=False)
        return

    await asyncio.gather(
        _pipe(reader, up_writer),
        _pipe(up_reader, writer),
        return_exceptions=True,
    )

    await rotator.on_request_done(endpoint.proxy_id, success=True)


async def _handle_http(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    method: str,
    target: str,
    headers: list[bytes],
    content_length: int,
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
        await rotator.on_request_done(endpoint.proxy_id, success=False)
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

    try:
        # Forward rewritten request line + original headers
        new_first = f"{method} {path} HTTP/1.1\r\n".encode()
        up_writer.write(new_first + b"".join(headers) + b"\r\n")

        # Forward request body
        is_chunked = any(
            b"transfer-encoding" in h.lower() and b"chunked" in h.lower()
            for h in headers
        )
        if is_chunked:
            # Relay chunked body chunk-by-chunk; terminate on the final "0\r\n" chunk
            while True:
                size_line = await asyncio.wait_for(reader.readline(), timeout=30)
                up_writer.write(size_line)
                try:
                    chunk_size = int(size_line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    break
                if chunk_size == 0:
                    # Terminal chunk - forward optional trailers + final blank line
                    while True:
                        trailer = await asyncio.wait_for(reader.readline(), timeout=10)
                        up_writer.write(trailer)
                        if trailer in (b"\r\n", b"\n", b""):
                            break
                    await up_writer.drain()
                    break
                data = await asyncio.wait_for(
                    reader.readexactly(chunk_size + 2), timeout=30
                )
                up_writer.write(data)
                await up_writer.drain()
        else:
            # Relay exact Content-Length bytes; skip for GET/HEAD with no body
            remaining = content_length
            while remaining > 0:
                chunk = await asyncio.wait_for(
                    reader.read(min(remaining, 65536)), timeout=30
                )
                if not chunk:
                    break
                up_writer.write(chunk)
                await up_writer.drain()
                remaining -= len(chunk)

        await up_writer.drain()

        # Stream response back; accumulate first 1 MB for BY_KEYWORD inspection
        await _pipe_checking_keywords(up_reader, writer, rotator, endpoint.proxy_id)
        await rotator.on_request_done(endpoint.proxy_id, success=True)
    except Exception:
        await rotator.on_request_done(endpoint.proxy_id, success=False)
        raise
    finally:
        try:
            up_writer.close()
        except Exception:
            pass


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
