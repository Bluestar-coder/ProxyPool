"""Generate platform icon files from assets/icon.png.

Mac:  assets/icon.icns  (via iconutil)
Win:  assets/icon.ico   (via Qt ICO writer, multi-size)
"""
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

ROOT = Path(__file__).parent.parent
src = ROOT / "assets" / "icon.png"
if not src.exists():
    print(f"ERROR: {src} not found")
    sys.exit(1)

pixmap = QPixmap(str(src))


def _scaled(size: int) -> QPixmap:
    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


# ── Windows ICO (multi-size, Qt supports ICO natively) ───────────────────────
ico_path = ROOT / "assets" / "icon.ico"
_scaled(256).toImage().save(str(ico_path), "ICO")
print(f"Generated {ico_path}")

# ── macOS ICNS ────────────────────────────────────────────────────────────────
if sys.platform == "darwin":
    iconset = ROOT / "assets" / "icon.iconset"
    iconset.mkdir(exist_ok=True)

    for name, size in [
        ("icon_16x16.png",      16),
        ("icon_16x16@2x.png",   32),
        ("icon_32x32.png",      32),
        ("icon_32x32@2x.png",   64),
        ("icon_128x128.png",   128),
        ("icon_128x128@2x.png",256),
        ("icon_256x256.png",   256),
        ("icon_256x256@2x.png",512),
        ("icon_512x512.png",   512),
        ("icon_512x512@2x.png",1024),
    ]:
        _scaled(size).save(str(iconset / name))

    icns_path = ROOT / "assets" / "icon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
        check=True,
    )
    import shutil
    shutil.rmtree(str(iconset))
    print(f"Generated {icns_path}")
