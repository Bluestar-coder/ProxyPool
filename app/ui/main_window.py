from __future__ import annotations
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QLineEdit, QTextEdit,
    QSplitter, QStatusBar, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from app.config import Config, DB_PATH
from app.db.database import Database
from app.db.models import Proxy, ValidationResult
from app.core.rotator import ProxyRotator, RotationMode
from app.core.socks_server import SocksServerThread
from app.core.validator import ValidatorThread
from app.ui.proxy_table import ProxyTableModel
from app.ui.dialogs.add_proxy import AddProxyDialog
from app.ui.dialogs.batch_add import BatchAddDialog
from app.ui.dialogs.auto_crawl import AutoCrawlDialog
from app.ui.dialogs.batch_manage import BatchManageDialog
from app.ui.dialogs.export_proxy import ExportDialog


_MODE_LABELS = [
    ("轮询代理模式", RotationMode.ROUND_ROBIN),
    ("Failover 模式", RotationMode.FAILOVER),
    ("根据次数更换", RotationMode.BY_COUNT),
    ("根据时间更换", RotationMode.BY_TIME),
    ("根据场景切换", RotationMode.BY_SCENE),
    ("根据关键词", RotationMode.BY_KEYWORD),
    ("固定代理", RotationMode.FIXED),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProxyPool")
        self.resize(1100, 700)

        self._db = Database(DB_PATH)
        self._db.initialize()
        self._config = Config.load(self._db)
        self._rotator = ProxyRotator()
        self._socks_thread: SocksServerThread | None = None
        self._validator_thread: ValidatorThread | None = None

        self._build_ui()
        self._refresh_table()

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())
        root.addLayout(self._build_action_bar())

        self._table = QTableView()
        self._model = ProxyTableModel()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("事件日志...")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._log)
        splitter.setSizes([550, 120])
        root.addWidget(splitter)

        root.addLayout(self._build_pagination())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._update_status("stopped")

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_start = QPushButton("启动代理")
        self._btn_start.setStyleSheet("background:#27ae60;color:white;padding:6px 14px;")
        self._btn_stop = QPushButton("关闭代理")
        self._btn_stop.setStyleSheet("background:#7f8c8d;color:white;padding:6px 14px;")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)

        self._mode_combo = QComboBox()
        for label, _ in _MODE_LABELS:
            self._mode_combo.addItem(label)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self._param_label = QLabel("次数:")
        self._param_spin = QSpinBox()
        self._param_spin.setRange(1, 9999)
        self._param_spin.setValue(self._config.rotation_params.get("threshold", 30))
        self._param_input = QLineEdit()
        self._param_input.setPlaceholderText("验证URL / 关键词...")
        self._param_input.setVisible(False)

        self._current_proxy_label = QLabel("当前代理: None")

        row.addWidget(self._btn_start)
        row.addWidget(self._btn_stop)
        row.addWidget(QLabel("模式:"))
        row.addWidget(self._mode_combo)
        row.addWidget(self._param_label)
        row.addWidget(self._param_spin)
        row.addWidget(self._param_input)
        row.addStretch()
        row.addWidget(self._current_proxy_label)
        return row

    def _build_action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        btns = [
            ("单个添加", self._on_add_single),
            ("批量添加", self._on_add_batch),
            ("自动爬取", self._on_auto_crawl),
            ("代理验证", self._on_validate),
            ("批量管理", self._on_batch_manage),
            ("导出代理", self._on_export),
        ]
        for label, slot in btns:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        return row

    def _build_pagination(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._page_label = QLabel("1")
        self._btn_next = QPushButton("▶")
        self._page_size_combo = QComboBox()
        for s in [10, 20, 50, 100]:
            self._page_size_combo.addItem(f"{s} / page", s)
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        self._page_size_combo.currentIndexChanged.connect(self._refresh_table)
        row.addStretch()
        row.addWidget(self._btn_prev)
        row.addWidget(self._page_label)
        row.addWidget(self._btn_next)
        row.addWidget(self._page_size_combo)
        return row

    # ── State ────────────────────────────────────────────────────────────────

    def _current_page(self) -> int:
        try:
            return int(self._page_label.text())
        except ValueError:
            return 1

    def _current_page_size(self) -> int:
        return self._page_size_combo.currentData() or 10

    def _refresh_table(self):
        page = self._current_page()
        size = self._current_page_size()
        proxies = self._db.get_all_proxies(page=page, page_size=size)
        total = self._db.count_proxies()
        self._model.load(proxies, total, page, size)
        self._rotator.load_proxies(self._db.get_all_proxies(status="valid"))
        cur = self._rotator.get_current()
        self._current_proxy_label.setText(f"当前代理: {cur.host}:{cur.port}" if cur else "当前代理: None")

    def _prev_page(self):
        p = max(1, self._current_page() - 1)
        self._page_label.setText(str(p))
        self._refresh_table()

    def _next_page(self):
        size = self._current_page_size()
        total = self._db.count_proxies()
        max_page = max(1, (total + size - 1) // size)
        p = min(max_page, self._current_page() + 1)
        self._page_label.setText(str(p))
        self._refresh_table()

    def _log_event(self, msg: str):
        self._log.append(msg)

    def _update_status(self, state: str):
        port = self._config.listen_port
        if state == "running":
            self._status_bar.showMessage(
                f"代理运行中: socks5://127.0.0.1:{port}", 0
            )
            self._status_bar.setStyleSheet("color: green;")
        elif state == "no_upstream":
            self._status_bar.showMessage(
                f"运行中（无可用上游代理）: socks5://127.0.0.1:{port}", 0
            )
            self._status_bar.setStyleSheet("color: orange;")
        else:
            self._status_bar.showMessage(f"代理关闭: socks5://127.0.0.1:{port}", 0)
            self._status_bar.setStyleSheet("color: red;")

    # ── SOCKS Server ─────────────────────────────────────────────────────────

    def _on_start(self):
        if self._socks_thread and self._socks_thread.isRunning():
            return
        self._socks_thread = SocksServerThread(self._rotator, self._config.listen_port)
        self._socks_thread.status_changed.connect(self._update_status)
        self._socks_thread.client_connected.connect(
            lambda s: self._log_event(f"[连接] {s}")
        )
        self._socks_thread.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._log_event(f"[服务器] 启动于 127.0.0.1:{self._config.listen_port}")

    def _on_stop(self):
        if self._socks_thread:
            self._socks_thread.stop()
            self._socks_thread.wait(3000)
            self._socks_thread = None
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._update_status("stopped")
        self._log_event("[服务器] 已关闭")

    # ── Rotation Mode ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, idx: int):
        _, mode = _MODE_LABELS[idx]
        show_spin = mode in (RotationMode.BY_COUNT,)
        show_time = mode in (RotationMode.BY_TIME,)
        show_input = mode in (RotationMode.BY_SCENE, RotationMode.BY_KEYWORD)
        self._param_spin.setVisible(show_spin or show_time)
        self._param_label.setVisible(show_spin or show_time)
        self._param_input.setVisible(show_input)
        if show_spin:
            self._param_label.setText("次数:")
        elif show_time:
            self._param_label.setText("分钟:")
        params = {}
        if show_spin:
            params["threshold"] = self._param_spin.value()
        elif show_time:
            params["interval_minutes"] = self._param_spin.value()
        elif show_input:
            params["trigger_word"] = self._param_input.text()
        self._rotator.set_mode(mode, **params)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_add_single(self):
        dlg = AddProxyDialog(self)
        if dlg.exec():
            p = dlg.get_proxy()
            if p:
                self._db.upsert_proxy(p)
                self._log_event(f"[添加] {p.host}:{p.port}")
                self._refresh_table()

    def _on_add_batch(self):
        dlg = BatchAddDialog(self)
        if dlg.exec():
            proxies = dlg.get_proxies()
            self._db.upsert_proxies(proxies)
            self._log_event(f"[批量添加] {len(proxies)} 个代理")
            self._refresh_table()

    def _on_auto_crawl(self):
        dlg = AutoCrawlDialog(self)
        if dlg.exec():
            config = dlg.get_config()
            from app.core.crawler_thread import CrawlerThread
            self._crawler_thread = CrawlerThread(config)
            self._crawler_thread.found.connect(
                lambda n: self._log_event(f"[爬取] 已发现 {n} 个候选代理")
            )
            self._crawler_thread.log.connect(self._log_event)
            self._crawler_thread.finished.connect(self._on_crawl_finished)
            self._crawler_thread.start()
            self._log_event("[爬取] 开始爬取...")

    def _on_crawl_finished(self, candidates: list):
        from app.db.models import Proxy
        proxies = [
            Proxy(host=c.host, port=c.port, type=c.type,
                  username=c.username, source=c.source)
            for c in candidates
        ]
        self._db.upsert_proxies(proxies)
        self._log_event(f"[爬取] 完成，新增/更新 {len(proxies)} 个代理")
        self._refresh_table()

    def _on_validate(self):
        all_proxies = self._db.get_all_proxies()
        if not all_proxies:
            QMessageBox.information(self, "提示", "没有可验证的代理")
            return
        self._validator_thread = ValidatorThread(
            proxies=all_proxies,
            endpoint=self._config.validator_endpoint,
            backup_endpoint=self._config.validator_endpoint_backup,
            timeout=self._config.validator_timeout,
            concurrency=self._config.validator_concurrency,
        )
        self._validator_thread.result_ready.connect(self._on_validation_result)
        self._validator_thread.progress.connect(
            lambda done, total: self._log_event(f"[验证] {done}/{total}")
        )
        self._validator_thread.finished.connect(self._refresh_table)
        self._validator_thread.start()
        self._log_event(f"[验证] 开始验证 {len(all_proxies)} 个代理")

    def _on_validation_result(self, result: ValidationResult):
        self._db.update_validation(result)

    def _on_batch_manage(self):
        selected_rows = sorted(set(i.row() for i in self._table.selectedIndexes()))
        selected_ids = [
            p.id for row in selected_rows
            if (p := self._model.get_proxy(row)) is not None
        ]
        dlg = BatchManageDialog(len(selected_ids), self)
        dlg.delete_selected.connect(lambda: self._delete_selected(selected_ids))
        dlg.delete_invalid.connect(self._delete_invalid)
        dlg.reset_status.connect(lambda: self._reset_status(selected_ids))
        dlg.validate_selected.connect(lambda: self._validate_selected(selected_ids))
        dlg.exec()

    def _delete_selected(self, proxy_ids: list[int]):
        if not proxy_ids:
            return
        self._db.delete_proxies(proxy_ids)
        self._log_event(f"[管理] 删除选中 {len(proxy_ids)} 个代理")
        self._refresh_table()

    def _delete_invalid(self):
        invalid = [p for p in self._db.get_all_proxies() if p.status == "invalid"]
        self._db.delete_proxies([p.id for p in invalid])
        self._log_event(f"[管理] 删除 {len(invalid)} 个无效代理")
        self._refresh_table()

    def _reset_status(self, proxy_ids: list[int]):
        if not proxy_ids:
            return
        self._db.reset_proxy_status(proxy_ids)
        self._log_event(f"[管理] 重置 {len(proxy_ids)} 个代理状态为未知")
        self._refresh_table()

    def _validate_selected(self, proxy_ids: list[int]):
        if not proxy_ids:
            return
        id_set = set(proxy_ids)
        proxies = [p for p in self._db.get_all_proxies() if p.id in id_set]
        if not proxies:
            return
        self._validator_thread = ValidatorThread(
            proxies=proxies,
            endpoint=self._config.validator_endpoint,
            backup_endpoint=self._config.validator_endpoint_backup,
            timeout=self._config.validator_timeout,
            concurrency=self._config.validator_concurrency,
        )
        self._validator_thread.result_ready.connect(self._on_validation_result)
        self._validator_thread.progress.connect(
            lambda done, total: self._log_event(f"[验证] {done}/{total}")
        )
        self._validator_thread.finished.connect(self._refresh_table)
        self._validator_thread.start()
        self._log_event(f"[验证] 开始验证选中 {len(proxies)} 个代理")

    def _on_export(self):
        proxies = self._db.get_all_proxies()
        dlg = ExportDialog(proxies, self)
        dlg.exec()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._on_stop()
        self._db.close()
        event.accept()
