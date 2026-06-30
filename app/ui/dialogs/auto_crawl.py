from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QLineEdit, QSpinBox, QLabel, QPlainTextEdit,
    QDialogButtonBox, QPushButton,
)
import keyring


_SERVICE = "ProxyPool"

_FOFA_QUERIES = """\
protocol=="socks5" && "Version:5 Method:No Authentication(0x00)" && country="CN"
protocol="socks5" && country="CN" && "No Authentication"
protocol="socks5" && country="CN" && "0x00"
port="1080" && country="CN" && "socks5" && "0x00"\
"""


class AutoCrawlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动爬取")
        self.resize(640, 420)

        # FOFA
        fofa_box = QGroupBox("FOFA")
        self._fofa_enabled = QCheckBox("启用")
        self._fofa_count = QSpinBox()
        self._fofa_count.setRange(1, 10000)
        self._fofa_count.setValue(500)
        self._fofa_key = QLineEdit()
        self._fofa_key.setPlaceholderText("email:key 格式")
        self._fofa_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._fofa_key.setMinimumWidth(200)
        saved_key = keyring.get_password(_SERVICE, "fofa_api_key") or ""
        if saved_key:
            self._fofa_key.setText(saved_key)
            self._fofa_enabled.setChecked(True)
        self._fofa_queries = QPlainTextEdit(_FOFA_QUERIES)
        self._fofa_queries.setFixedHeight(120)
        self._fofa_queries.setPlaceholderText("每行一条查询语句")

        fofa_top = QHBoxLayout()
        fofa_top.addWidget(self._fofa_enabled)
        fofa_top.addWidget(QLabel("数量"))
        fofa_top.addWidget(self._fofa_count)
        fofa_top.addWidget(QLabel("API Key"))
        fofa_top.addWidget(self._fofa_key)
        fofa_top.addStretch()

        fofa_layout = QVBoxLayout(fofa_box)
        fofa_layout.addLayout(fofa_top)
        fofa_layout.addWidget(QLabel("查询语句（每行一条，每条查询数量上限为上面设置的数量）"))
        fofa_layout.addWidget(self._fofa_queries)

        # 免费代理
        free_box = QGroupBox("免费代理")
        self._free_enabled = QCheckBox("启用")
        self._free_count = QSpinBox()
        self._free_count.setRange(1, 500)
        self._free_count.setValue(50)
        free_row = QHBoxLayout()
        free_row.addWidget(self._free_enabled)
        free_row.addWidget(QLabel("数量上限"))
        free_row.addWidget(self._free_count)
        free_row.addStretch()
        free_box.setLayout(free_row)

        # Buttons
        buttons = QDialogButtonBox()
        save_btn = QPushButton("开始爬取")
        cancel_btn = QPushButton("取消")
        save_btn.setObjectName("startBtn")
        buttons.addButton(save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(fofa_box)
        layout.addWidget(free_box)
        layout.addStretch()
        layout.addWidget(buttons)

    def _on_accept(self):
        val = self._fofa_key.text().strip()
        if val:
            keyring.set_password(_SERVICE, "fofa_api_key", val)
        self.accept()

    def get_config(self) -> dict:
        raw = self._fofa_queries.toPlainText()
        queries = [q.strip() for q in raw.splitlines() if q.strip()]
        return {
            "fofa": {
                "enabled": self._fofa_enabled.isChecked(),
                "limit": self._fofa_count.value(),
                "api_key": self._fofa_key.text().strip(),
                "queries": queries,
            },
            "free": {
                "enabled": self._free_enabled.isChecked(),
                "limit": self._free_count.value(),
            },
        }
