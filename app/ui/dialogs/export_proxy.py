from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QVBoxLayout,
)

from app.db.models import Proxy


class ExportDialog(QDialog):
    def __init__(self, proxies: list[Proxy], parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出代理")
        self._proxies = proxies

        self._fmt = QComboBox()
        self._fmt.addItems(["txt (host:port)", "txt (url)", "csv", "json",
                            "Clash (YAML)", "Surge (conf)"])
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
        try:
            _write(Path(path), proxies, fmt, redact)
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "导出失败", f"无法写入文件：{exc}")
            return
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
    elif fmt == "Clash (YAML)":
        path.write_text(_to_clash_yaml(proxies, redact), encoding="utf-8")
    elif fmt == "Surge (conf)":
        path.write_text(_to_surge_conf(proxies, redact), encoding="utf-8")


def _proxy_name(p: Proxy, idx: int) -> str:
    region = f"-{p.region}" if p.region else ""
    return f"{p.type.upper()}{region}-{p.host}:{p.port}-{idx}"


def _to_clash_yaml(proxies: list[Proxy], redact: bool) -> str:
    proxy_list = []
    for i, p in enumerate(proxies):
        pwd = "***" if redact else p.password
        entry: dict = {
            "name": _proxy_name(p, i),
            "type": p.type,
            "server": p.host,
            "port": p.port,
        }
        if p.username:
            entry["username"] = p.username
            entry["password"] = pwd
        proxy_list.append(entry)
    return yaml.dump({"proxies": proxy_list}, allow_unicode=True, default_flow_style=False)


def _to_surge_conf(proxies: list[Proxy], redact: bool) -> str:
    lines = ["[Proxy]"]
    skipped = 0
    for i, p in enumerate(proxies):
        name = _proxy_name(p, i)
        pwd = "***" if redact else p.password
        if "," in name or "," in p.host or "," in p.username or "," in pwd:
            skipped += 1
            continue
        if p.username:
            lines.append(f"{name} = {p.type}, {p.host}, {p.port}, {p.username}, {pwd}")
        else:
            lines.append(f"{name} = {p.type}, {p.host}, {p.port}")
    if skipped:
        lines.append(
            f"# {skipped} proxies skipped (credentials contain commas, unsupported by Surge format)"
        )
    return "\n".join(lines) + "\n"
