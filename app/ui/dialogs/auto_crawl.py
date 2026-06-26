from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QLineEdit, QSpinBox, QComboBox, QLabel,
    QDialogButtonBox, QPushButton, QScrollArea, QWidget,
)
import keyring


_SERVICE = "ProxyPool"
_FOFA_DEFAULT = 'protocol=="socks5" && "Version:5 Method:No Authentication(0x00)"'
_QUAKE_DEFAULT = 'service:socks5 AND country:"CN"'
_HUNTER_DEFAULT = "socks5"


class SourceRow(QWidget):
    def __init__(self, name: str, key_label: str,
                 default_query: str, default_count: int, parent=None):
        super().__init__(parent)
        self._name = name
        self._enabled = QCheckBox("启用")
        self._count = QSpinBox()
        self._count.setRange(1, 50000)
        self._count.setValue(default_count)
        self._key = QLineEdit()
        self._key.setPlaceholderText(f"{key_label} (存储于系统 keyring)")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        saved_key = keyring.get_password(_SERVICE, f"{name}_api_key") or ""
        if saved_key:
            self._key.setText(saved_key)
            self._enabled.setChecked(True)
        self._query = QLineEdit(default_query)

        top = QHBoxLayout()
        top.addWidget(QLabel(name.upper()))
        top.addWidget(self._enabled)
        top.addWidget(QLabel("查询数量"))
        top.addWidget(self._count)
        top.addWidget(QLabel(f"{key_label}"))
        top.addWidget(self._key)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(QLabel(f"{name.upper()} 语法"))
        layout.addWidget(self._query)

    def save_key(self):
        val = self._key.text().strip()
        if val:
            keyring.set_password(_SERVICE, f"{self._name}_api_key", val)

    def config(self) -> dict:
        return {
            "enabled": self._enabled.isChecked(),
            "limit": self._count.value(),
            "api_key": self._key.text().strip(),
            "query": self._query.text().strip(),
        }


class AutoCrawlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动爬取")
        self.resize(680, 580)

        self._fofa = SourceRow("fofa", "FofaKey", _FOFA_DEFAULT, 10000)
        self._quake = SourceRow("quake", "QuaKeKey", _QUAKE_DEFAULT, 300)
        self._hunter = SourceRow("hunter", "HunterKey", _HUNTER_DEFAULT, 200)

        # 免费代理
        free_box = QGroupBox("免费代理")
        self._free_enabled = QCheckBox("启用")
        self._free_count = QSpinBox()
        self._free_count.setRange(1, 200)
        self._free_count.setValue(20)
        self._free_type = QComboBox()
        self._free_type.addItems(["socks5", "socks4", "http"])
        free_row = QHBoxLayout()
        free_row.addWidget(self._free_enabled)
        free_row.addWidget(QLabel("查询数量"))
        free_row.addWidget(self._free_count)
        free_row.addWidget(QLabel("代理类型"))
        free_row.addWidget(self._free_type)
        free_row.addStretch()
        free_box.setLayout(free_row)

        # 凭据补全
        brute_box = QGroupBox("凭据补全")
        self._brute_enabled = QCheckBox("未启用")
        self._brute_warn = QLabel(
            "启用后将对所有代理尝试已有凭据，仅用于您拥有授权的代理"
        )
        self._brute_warn.setStyleSheet("color: orange;")
        self._brute_confirm = QCheckBox("我确认上述代理均属于我或我有权限测试")
        brute_layout = QVBoxLayout()
        brute_layout.addWidget(self._brute_enabled)
        brute_layout.addWidget(self._brute_warn)
        brute_layout.addWidget(self._brute_confirm)
        brute_box.setLayout(brute_layout)
        self._brute_enabled.toggled.connect(
            lambda checked: self._brute_confirm.setEnabled(checked)
        )

        buttons = QDialogButtonBox()
        save_btn = QPushButton("保存并爬取")
        cancel_btn = QPushButton("取消")
        save_btn.setStyleSheet("background:#27ae60;color:white;")
        cancel_btn.setStyleSheet("background:#e74c3c;color:white;")
        buttons.addButton(save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        content = QWidget()
        vbox = QVBoxLayout(content)
        vbox.addWidget(self._fofa)
        vbox.addWidget(self._quake)
        vbox.addWidget(self._hunter)
        vbox.addWidget(free_box)
        vbox.addWidget(brute_box)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

    def _on_accept(self):
        for src in [self._fofa, self._quake, self._hunter]:
            src.save_key()
        self.accept()

    def get_config(self) -> dict:
        return {
            "fofa": self._fofa.config(),
            "quake": self._quake.config(),
            "hunter": self._hunter.config(),
            "free": {
                "enabled": self._free_enabled.isChecked(),
                "limit": self._free_count.value(),
                "proxy_type": self._free_type.currentText(),
            },
            "bruteforce": {
                "enabled": (self._brute_enabled.isChecked()
                            and self._brute_confirm.isChecked()),
            },
        }
