from __future__ import annotations
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel,
    QDialogButtonBox, QComboBox, QHBoxLayout,
)
from app.db.models import Proxy

_URL_RE = re.compile(
    r"^(?P<type>socks5|socks4|https?)"
    r"://(?:(?P<user>[^:@]+):(?P<pass>[^@]+)@)?"
    r"(?P<host>[^:]+):(?P<port>\d+)$"
)
_PLAIN_RE = re.compile(r"^(?P<host>[^:]+):(?P<port>\d+)$")


def parse_proxy_line(line: str, default_type: str = "socks5") -> Proxy | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = _URL_RE.match(line)
    if m:
        return Proxy(
            host=m["host"], port=int(m["port"]), type=m["type"],
            username=m["user"] or "", password=m["pass"] or "", source="manual",
        )
    m = _PLAIN_RE.match(line)
    if m:
        return Proxy(host=m["host"], port=int(m["port"]),
                     type=default_type, source="manual")
    return None


class BatchAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量添加代理")
        self.resize(520, 400)

        self._default_type = QComboBox()
        self._default_type.addItems(["socks5", "socks4", "http"])

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("默认类型:"))
        type_row.addWidget(self._default_type)
        type_row.addStretch()

        self._text = QTextEdit()
        self._text.setPlaceholderText(
            "每行一个代理，支持格式：\n"
            "socks5://host:port\n"
            "socks5://user:pass@host:port\n"
            "host:port"
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(type_row)
        layout.addWidget(QLabel("代理列表:"))
        layout.addWidget(self._text)
        layout.addWidget(buttons)

    def get_proxies(self) -> list[Proxy]:
        dtype = self._default_type.currentText()
        proxies = []
        for line in self._text.toPlainText().splitlines():
            p = parse_proxy_line(line, dtype)
            if p:
                proxies.append(p)
        return proxies
