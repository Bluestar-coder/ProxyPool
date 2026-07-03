import logging
import sys
from pathlib import Path
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

logging.basicConfig(
    level=logging.DEBUG,
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
