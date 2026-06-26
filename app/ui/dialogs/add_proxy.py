from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QDialogButtonBox, QVBoxLayout, QCheckBox,
)
from app.db.models import Proxy


class AddProxyDialog(QDialog):
    def __init__(self, parent=None, proxy: Proxy | None = None):
        super().__init__(parent)
        self.setWindowTitle("添加代理" if proxy is None else "编辑代理")
        self._proxy = proxy

        self._type = QComboBox()
        self._type.addItems(["socks5", "socks4", "http", "https"])
        self._host = QLineEdit()
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(1080)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._validate_now = QCheckBox("立即验证")

        form = QFormLayout()
        form.addRow("类型", self._type)
        form.addRow("Host", self._host)
        form.addRow("Port", self._port)
        form.addRow("用户名", self._username)
        form.addRow("密码", self._password)
        form.addRow("", self._validate_now)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if proxy:
            self._type.setCurrentText(proxy.type)
            self._host.setText(proxy.host)
            self._port.setValue(proxy.port)
            self._username.setText(proxy.username)

    def get_proxy(self) -> Proxy | None:
        host = self._host.text().strip()
        if not host:
            return None
        return Proxy(
            id=self._proxy.id if self._proxy else 0,
            host=host,
            port=self._port.value(),
            type=self._type.currentText(),
            username=self._username.text().strip(),
            password=self._password.text(),
            source="manual",
        )

    def should_validate(self) -> bool:
        return self._validate_now.isChecked()
