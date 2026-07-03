import asyncio
import gzip
import os
import io
import platform
import socket
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

BINARY_DIR = Path.home() / ".proxy_pool" / "core"
_EXE = ".exe" if platform.system() == "Windows" else ""
BINARY_PATH = BINARY_DIR / f"mihomo{_EXE}"

_GITHUB_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("armv7l", "armv7"):
        return "armv7"
    return m


def _platform_asset_name(tag: str) -> str:
    sys = platform.system()
    arch = _arch()
    if sys == "Windows":
        return f"mihomo-windows-{arch}-{tag}.zip"
    if sys == "Darwin":
        return f"mihomo-darwin-{arch}-{tag}.gz"
    return f"mihomo-linux-{arch}-{tag}.gz"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def ensure_binary(log_cb: Callable[[str], None] | None = None) -> bool:
    def _log(msg: str) -> None:
        if log_cb:
            log_cb(f"[订阅] {msg}")

    if BINARY_PATH.exists():
        return True

    _log("首次使用，正在从 GitHub 下载 mihomo 内核...")
    import json

    loop = asyncio.get_running_loop()

    def _fetch_release():
        with urlopen(_GITHUB_API, timeout=15) as r:
            return json.loads(r.read())

    try:
        release = await loop.run_in_executor(None, _fetch_release)
    except Exception as e:
        _log(f"获取 release 信息失败: {e}")
        return False

    tag = release.get("tag_name", "")
    asset_name = _platform_asset_name(tag)
    download_url = next(
        (a["browser_download_url"] for a in release.get("assets", [])
         if a["name"] == asset_name),
        None,
    )

    if not download_url:
        _log(f"未找到平台资源 {asset_name}")
        return False

    _log(f"下载 {asset_name}...")

    def _download():
        with urlopen(download_url, timeout=120) as r:
            return r.read()

    try:
        content = await loop.run_in_executor(None, _download)
    except Exception as e:
        _log(f"下载失败: {e}")
        return False

    BINARY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                entry = next(
                    (n for n in zf.namelist() if "mihomo" in n.lower()),
                    None,
                )
                if not entry:
                    _log("zip 内未找到 mihomo 可执行文件")
                    return False
                data = zf.read(entry)
        else:
            data = gzip.decompress(content)
    except Exception as e:
        _log(f"解压失败: {e}")
        return False

    # Atomic write: write to temp then rename, so a crash mid-write
    # doesn't leave a corrupt binary that exists() would accept next run
    tmp_path = BINARY_DIR / f".mihomo_tmp_{os.getpid()}"
    try:
        tmp_path.write_bytes(data)
        tmp_path.chmod(0o755)
        os.replace(tmp_path, BINARY_PATH)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        _log(f"写入失败: {e}")
        return False

    _log("mihomo 内核下载完成")
    return True


class MihomoProcess:
    def __init__(self, config_path: str, api_port: int) -> None:
        self._config_path = config_path
        self._api_port = api_port
        self._proc: subprocess.Popen | None = None

    def start(self, timeout: float = 5.0) -> bool:
        for attempt in range(2):
            port = self._api_port if attempt == 0 else _find_free_port()
            if attempt == 1:
                self._api_port = port

            try:
                self._proc = subprocess.Popen(
                    [str(BINARY_PATH), "-f", self._config_path,
                     "-ext-ctl", f"127.0.0.1:{port}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                return False

            # Brief wait to detect immediate exit (port conflict)
            time.sleep(0.2)
            if self._proc.poll() is not None:
                self._proc = None
                continue

            # Poll until mihomo REST API responds
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/version", timeout=1) as r:
                        if r.status == 200:
                            return True
                except Exception:
                    pass
                if self._proc.poll() is not None:
                    self._proc = None
                    break
                time.sleep(0.2)

            # /version did not respond within timeout - process started but isn't ready
            if self._proc is not None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        self._proc.kill()
                        self._proc.wait()
                    except Exception:
                        pass
                self._proc = None
            return False

        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                self._proc.kill()
                self._proc.wait()
            except Exception:
                pass
        except Exception:
            pass
        finally:
            self._proc = None

    @property
    def api_port(self) -> int:
        return self._api_port
