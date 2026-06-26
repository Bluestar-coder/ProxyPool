from __future__ import annotations
import csv
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox,
    QDialogButtonBox, QLabel, QFileDialog,
)
from app.db.models import Proxy


class ExportDialog(QDialog):
    def __init__(self, proxies: list[Proxy], parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出代理")
        self._proxies = proxies

        self._fmt = QComboBox()
        self._fmt.addItems(["txt (host:port)", "txt (url)", "csv", "json"])
        self._valid_only = QCheckBox("仅导出有效代理")
        self._valid_only.setChecked(True)
        self._redact = QCheckBox("脱敏密码（推荐）")
        self._redact.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("导出格式:"))
        layout.addWidget(self._fmt)
        layout.addWidget(self._valid_only)
        layout.addWidget(self._redact)
        layout.addWidget(buttons)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存文件", "", "All Files (*)")
        if not path:
            return
        proxies = self._proxies
        if self._valid_only.isChecked():
            proxies = [p for p in proxies if p.status == "valid"]
        redact = self._redact.isChecked()
        fmt = self._fmt.currentText()
        _write(Path(path), proxies, fmt, redact)
        self.accept()


def _write(path: Path, proxies: list[Proxy], fmt: str, redact: bool):
    if fmt.startswith("txt (host"):
        path.write_text("\n".join(f"{p.host}:{p.port}" for p in proxies), encoding="utf-8")
    elif fmt.startswith("txt (url"):
        lines = [p.redacted_url if redact else p.url for p in proxies]
        path.write_text("\n".join(lines), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["host", "port", "type", "username", "password",
                        "region", "latency", "status", "anonymity"])
            for p in proxies:
                w.writerow([p.host, p.port, p.type, p.username,
                            "***" if redact else p.password,
                            p.region, p.latency, p.status, p.anonymity])
    elif fmt == "json":
        data = []
        for p in proxies:
            d = {"host": p.host, "port": p.port, "type": p.type,
                 "username": p.username, "region": p.region,
                 "latency": p.latency, "status": p.status}
            if not redact:
                d["password"] = p.password
            data.append(d)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
