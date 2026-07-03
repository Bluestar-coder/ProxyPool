from __future__ import annotations

import json
from pathlib import Path
from urllib.request import pathname2url

import keyring
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

_SERVICE = "ProxyPool"
_KEYRING_KEY = "subscription_urls"
_MAX_URL_DISPLAY = 80


def _load_urls() -> list[str]:
    raw = keyring.get_password(_SERVICE, _KEYRING_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _save_urls(urls: list[str]) -> None:
    keyring.set_password(_SERVICE, _KEYRING_KEY, json.dumps(urls))


def _truncate(url: str, max_len: int = _MAX_URL_DISPLAY) -> str:
    return url if len(url) <= max_len else url[:max_len] + "..."


def _display_label(url: str) -> str:
    if url.startswith("file://"):
        return f"[文件] {Path(url[7:]).name}"
    return _truncate(url)


class SubscriptionDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("订阅管理")
        self.resize(620, 380)

        self._urls: list[str] = _load_urls()

        # --- URL list group ---
        url_box = QGroupBox("订阅链接")
        self._list = QListWidget()
        for url in self._urls:
            self._list.addItem(_display_label(url))

        add_btn = QPushButton("添加链接")
        upload_btn = QPushButton("上传文件")
        del_btn = QPushButton("删除")
        add_btn.clicked.connect(self._on_add)
        upload_btn.clicked.connect(self._on_upload_file)
        del_btn.clicked.connect(self._on_delete)

        btn_col = QVBoxLayout()
        btn_col.addWidget(add_btn)
        btn_col.addWidget(upload_btn)
        btn_col.addWidget(del_btn)
        btn_col.addStretch()

        url_row = QHBoxLayout()
        url_row.addWidget(self._list)
        url_row.addLayout(btn_col)
        url_box.setLayout(url_row)

        # --- Concurrency row ---
        self._concurrency = QSpinBox()
        self._concurrency.setRange(1, 100)
        self._concurrency.setValue(20)

        conc_row = QHBoxLayout()
        conc_row.addWidget(QLabel("并发数"))
        conc_row.addWidget(self._concurrency)
        conc_row.addStretch()

        # --- Dialog buttons ---
        buttons = QDialogButtonBox()
        import_btn = QPushButton("导入")
        cancel_btn = QPushButton("取消")
        import_btn.setObjectName("importBtn")
        buttons.addButton(import_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_import)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(url_box)
        layout.addLayout(conc_row)
        layout.addStretch()
        layout.addWidget(buttons)

    def _on_add(self) -> None:
        text, ok = QInputDialog.getText(self, "添加订阅", "请输入订阅链接 URL：")
        if not ok or not text.strip():
            return
        url = text.strip()
        self._urls.append(url)
        self._list.addItem(_display_label(url))
        _save_urls(self._urls)

    def _on_upload_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择订阅文件",
            "",
            "YAML 文件 (*.yaml *.yml);;文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        url = "file://" + pathname2url(path)
        self._urls.append(url)
        self._list.addItem(_display_label(url))
        _save_urls(self._urls)

    def _on_delete(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
        self._urls.pop(row)
        _save_urls(self._urls)

    def _on_import(self) -> None:
        if not self._urls:
            QMessageBox.information(self, "提示", "请先添加至少一条订阅链接")
            return
        self.accept()

    def get_config(self) -> dict:
        return {
            "urls": list(self._urls),
            "concurrency": self._concurrency.value(),
        }
