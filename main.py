import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

load_dotenv()

def _resolve_log_level() -> int:
    raw = os.environ.get("PROXYPOOL_LOG_LEVEL", "INFO").upper()
    return getattr(logging, raw, logging.INFO)


logging.basicConfig(
    level=_resolve_log_level(),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

_ICON_PATH = Path(__file__).parent / "assets" / "icon.png"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ProxyPool")
    if _ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(_ICON_PATH)))
    from app.ui.main_window import MainWindow
    window = MainWindow()
    if _ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(_ICON_PATH)))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
