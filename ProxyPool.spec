# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Collect PyQt6 + heavy deps ────────────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []

for pkg in ("PyQt6", "aiohttp", "aiohttp_socks", "python_socks", "keyring",
            "opencc", "bs4", "lxml", "platformdirs", "yaml"):
    d, b, h = collect_all(pkg)
    datas     += d
    binaries  += b
    hiddenimports += h

# App assets
datas += [("assets", "assets")]

# Hidden imports PyInstaller can't auto-detect
hiddenimports += [
    # dynamic importlib.import_module in crawlers/__init__.py
    "app.core.crawlers.base",
    "app.core.crawlers.fofa",
    "app.core.crawlers.free_sites",
    "app.core.crawlers.hunter",
    "app.core.crawlers.quake",
    # conditional imports in main_window.py
    "app.core.http_proxy",
    "app.core.rest_api",
    "app.core.socks_server",
    "app.core.subscription",
    "app.ui.dialogs.add_proxy",
    "app.ui.dialogs.auto_crawl",
    "app.ui.dialogs.batch_add",
    "app.ui.dialogs.batch_manage",
    "app.ui.dialogs.export_proxy",
    "app.ui.dialogs.subscription",
    # keyring platform backends
    "keyring.backends.macOS",
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.fail",
    "keyring.backends.null",
    # stdlib async transports
    "asyncio.selector_events",
    "asyncio.proactor_events",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_qt", "pytest_asyncio", "pytest_mock",
              "_pytest", "hypothesis"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Platform-specific icon ────────────────────────────────────────────────────
_icon = "assets/icon.icns" if sys.platform == "darwin" else "assets/icon.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProxyPool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    argv_emulation=False,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ProxyPool",
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ProxyPool.app",
        icon="assets/icon.icns",
        bundle_identifier="com.proxypool.app",
        info_plist={
            "CFBundleName": "ProxyPool",
            "CFBundleDisplayName": "ProxyPool",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
        },
    )
