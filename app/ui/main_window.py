from __future__ import annotations
from datetime import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QLineEdit, QTextEdit,
    QSplitter, QStatusBar, QMessageBox, QMenuBar, QMenu,
    QFrame, QTabWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from app.config import Config, DB_PATH
from app.db.database import Database
from app.db.models import Proxy, ValidationResult
from app.core.crawler_thread import CrawlerThread
from app.core.http_proxy import HttpProxyThread
from app.core.rest_api import RestApiThread
from app.core.rotator import ProxyRotator, RotationMode
from app.core.socks_server import SocksServerThread
from app.core.validator import ValidatorThread
from app.ui.proxy_table import ProxyTableModel
from app.ui.themes import THEMES, DEFAULT_THEME, build_stylesheet
from app.ui.dialogs.add_proxy import AddProxyDialog
from app.ui.dialogs.batch_add import BatchAddDialog
from app.ui.dialogs.auto_crawl import AutoCrawlDialog
from app.ui.dialogs.batch_manage import BatchManageDialog
from app.ui.dialogs.export_proxy import ExportDialog
from app.ui.dialogs.subscription import SubscriptionDialog
from app.core.subscription import SubscriptionThread


_MODE_LABELS = [
    ("轮询", RotationMode.ROUND_ROBIN),
    ("故障转移", RotationMode.FAILOVER),
    ("按次数", RotationMode.BY_COUNT),
    ("按时间", RotationMode.BY_TIME),
    ("按场景", RotationMode.BY_SCENE),
    ("按关键词", RotationMode.BY_KEYWORD),
    ("固定", RotationMode.FIXED),
]

_AUTO_MAINTENANCE_INTERVAL_MS = 5 * 60 * 1000
_AUTO_REPLENISH_VALID_THRESHOLD = 50  # only auto-crawl when valid proxies drop below this
_AUTO_REPLENISH_CRAWL_LIMIT = 100     # cap per-source crawl size for auto-replenish


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProxyPool")
        self.resize(1200, 750)

        self._db = Database(DB_PATH)
        self._db.initialize()
        self._config = Config.load(self._db)
        self._rotator = ProxyRotator()
        self._socks_thread: SocksServerThread | None = None
        self._rest_api_thread: RestApiThread | None = None
        self._http_proxy_thread: HttpProxyThread | None = None
        self._crawler_thread: CrawlerThread | None = None
        self._validator_thread: ValidatorThread | None = None
        self._speed_thread = None  # SpeedTestThread
        self._subscription_thread: SubscriptionThread | None = None
        self._val_done = 0
        self._current_theme = self._db.get_config("ui_theme", DEFAULT_THEME)
        self._status_state = "stopped"
        self._auto_maintenance_timer = QTimer(self)
        self._auto_maintenance_timer.timeout.connect(self._on_auto_maintenance_tick)

        self._build_menu_bar()
        self._build_ui()
        self._apply_theme(self._current_theme)
        self._refresh_table()

        if self._config.auto_maintenance_enabled:
            self._auto_maintenance_timer.start(_AUTO_MAINTENANCE_INTERVAL_MS)

        if self._db.migration_failed_hosts:
            failed = self._db.migration_failed_hosts
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    self,
                    "密码迁移警告",
                    f"{len(failed)} 个代理密码未能迁移到系统 Keyring，仍明文存储:\n"
                    + "\n".join(failed),
                ),
            )

    # ── Menu Bar ─────────────────────────────────────────────────────────────

    def _build_menu_bar(self):
        bar: QMenuBar = self.menuBar()

        file_menu: QMenu = bar.addMenu("文件")
        export_act = QAction("导出代理...", self)
        export_act.triggered.connect(self._on_export)
        file_menu.addAction(export_act)
        file_menu.addSeparator()
        quit_act = QAction("退出", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu: QMenu = bar.addMenu("视图")
        theme_menu: QMenu = view_menu.addMenu("主题")
        for name in THEMES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(name == self._current_theme)
            act.triggered.connect(lambda checked, n=name: self._on_theme_selected(n))
            theme_menu.addAction(act)
        self._theme_menu = theme_menu

        proxy_menu: QMenu = bar.addMenu("代理")
        add_act = QAction("单个添加...", self)
        add_act.triggered.connect(self._on_add_single)
        batch_act = QAction("批量添加...", self)
        batch_act.triggered.connect(self._on_add_batch)
        crawl_act = QAction("自动爬取...", self)
        crawl_act.triggered.connect(self._on_auto_crawl)
        validate_act = QAction("全部验证", self)
        validate_act.triggered.connect(self._on_validate)
        proxy_menu.addActions([add_act, batch_act, crawl_act])
        proxy_menu.addSeparator()
        proxy_menu.addAction(validate_act)
        proxy_menu.addSeparator()
        self._auto_maintenance_act = QAction(
            f"定时自动维护（每 {_AUTO_MAINTENANCE_INTERVAL_MS // 60000} 分钟）", self
        )
        self._auto_maintenance_act.setCheckable(True)
        self._auto_maintenance_act.setChecked(self._config.auto_maintenance_enabled)
        self._auto_maintenance_act.toggled.connect(self._on_toggle_auto_maintenance)
        proxy_menu.addAction(self._auto_maintenance_act)

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        root.addLayout(self._build_server_bar())
        root.addWidget(self._build_divider())
        root.addLayout(self._build_action_bar())
        root.addLayout(self._build_stats_bar())

        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._build_all_proxies_tab(), "全部代理")
        self._tab_widget.addTab(self._build_sub_tab(), "订阅代理")
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(130)
        self._log.setPlaceholderText("事件日志...")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._tab_widget)
        splitter.addWidget(self._log)
        splitter.setSizes([560, 130])
        root.addWidget(splitter)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._update_status("stopped")

    def _build_all_proxies_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        layout.addLayout(self._build_filter_bar())

        self._table = QTableView()
        self._model = ProxyTableModel()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)
        layout.addWidget(self._table)

        layout.addLayout(self._build_pagination())
        return widget

    def _build_sub_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        hint = QLabel("订阅节点 · 按类型分组排序")
        hint.setStyleSheet("color: #888; font-size: 12px; padding: 2px 0;")
        layout.addWidget(hint)
        self._sub_table = QTableView()
        self._sub_model = ProxyTableModel()
        self._sub_table.setModel(self._sub_model)
        self._sub_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._sub_table.setAlternatingRowColors(True)
        self._sub_table.setSortingEnabled(True)
        self._sub_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._sub_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._sub_table.verticalHeader().setVisible(False)
        self._sub_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sub_table.customContextMenuRequested.connect(self._on_sub_table_context_menu)
        layout.addWidget(self._sub_table)
        return widget

    def _build_server_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._btn_start = QPushButton("▶  启动代理")
        self._btn_start.setObjectName("startBtn")
        self._btn_stop = QPushButton("■  关闭代理")
        self._btn_stop.setObjectName("stopBtn")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)

        sep = QLabel("|")
        sep.setStyleSheet("color: #555; margin: 0 4px;")

        self._mode_combo = QComboBox()
        for label, _ in _MODE_LABELS:
            self._mode_combo.addItem(label)
        # The popup defaults to the combo's own (closed) width, which is
        # sized to the current short item - widen it to fit the longest
        # label so items like "按关键词" don't get clipped in the dropdown.
        fm = self._mode_combo.fontMetrics()
        widest = max(fm.horizontalAdvance(label) for label, _ in _MODE_LABELS)
        self._mode_combo.view().setMinimumWidth(widest + 40)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self._param_label = QLabel("次数:")
        self._param_spin = QSpinBox()
        self._param_spin.setRange(1, 9999)
        self._param_spin.setValue(self._config.rotation_params.get("threshold", 30))
        self._param_spin.setFixedWidth(70)
        self._param_spin.valueChanged.connect(lambda _: self._sync_rotation_mode())
        self._param_input = QLineEdit()
        self._param_input.setPlaceholderText("验证URL / 关键词...")
        self._param_input.setFixedWidth(160)
        self._param_input.setVisible(False)
        self._param_input.textChanged.connect(lambda _: self._sync_rotation_mode())

        self._current_proxy_label = QLabel("当前代理: -")
        self._current_proxy_label.setObjectName("statLabel")

        row.addWidget(self._btn_start)
        row.addWidget(self._btn_stop)
        row.addWidget(sep)
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
        row.setSpacing(6)

        for label, slot in [
            ("单个添加", self._on_add_single),
            ("批量添加", self._on_add_batch),
            ("自动爬取", self._on_auto_crawl),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)

        self._btn_validate = QPushButton("代理验证")
        self._btn_validate.clicked.connect(self._on_validate)
        row.addWidget(self._btn_validate)

        self._btn_validate_pause = QPushButton("暂停验证")
        self._btn_validate_pause.clicked.connect(self._on_validate_pause)
        self._btn_validate_pause.setVisible(False)
        row.addWidget(self._btn_validate_pause)

        self._btn_validate_stop = QPushButton("停止验证")
        self._btn_validate_stop.clicked.connect(self._on_validate_stop)
        self._btn_validate_stop.setVisible(False)
        row.addWidget(self._btn_validate_stop)

        self._btn_speed = QPushButton("速度测试")
        self._btn_speed.clicked.connect(self._on_speed_test)
        row.addWidget(self._btn_speed)

        self._btn_speed_pause = QPushButton("暂停测速")
        self._btn_speed_pause.clicked.connect(self._on_speed_pause)
        self._btn_speed_pause.setVisible(False)
        row.addWidget(self._btn_speed_pause)

        self._btn_speed_stop = QPushButton("停止测速")
        self._btn_speed_stop.clicked.connect(self._on_speed_stop)
        self._btn_speed_stop.setVisible(False)
        row.addWidget(self._btn_speed_stop)

        for label, slot in [
            ("批量管理", self._on_batch_manage),
            ("订阅", self._on_subscription),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)

        row.addStretch()
        return row

    def _set_validator_state(self, state: str) -> None:
        if state == "idle":
            self._btn_validate.setEnabled(True)
            self._btn_validate_pause.setVisible(False)
            self._btn_validate_stop.setVisible(False)
        elif state == "running":
            self._btn_validate.setEnabled(False)
            self._btn_validate_pause.setText("暂停验证")
            self._btn_validate_pause.setVisible(True)
            self._btn_validate_stop.setVisible(True)
        elif state == "paused":
            self._btn_validate.setEnabled(False)
            self._btn_validate_pause.setText("继续验证")
            self._btn_validate_pause.setVisible(True)
            self._btn_validate_stop.setVisible(True)

    def _set_speed_state(self, state: str) -> None:
        if state == "idle":
            self._btn_speed.setEnabled(True)
            self._btn_speed_pause.setVisible(False)
            self._btn_speed_stop.setVisible(False)
        elif state == "running":
            self._btn_speed.setEnabled(False)
            self._btn_speed_pause.setText("暂停测速")
            self._btn_speed_pause.setVisible(True)
            self._btn_speed_stop.setVisible(True)
        elif state == "paused":
            self._btn_speed.setEnabled(False)
            self._btn_speed_pause.setText("继续测速")
            self._btn_speed_pause.setVisible(True)
            self._btn_speed_stop.setVisible(True)

    def _build_stats_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        def _pair(title: str, val_name: str) -> tuple[QLabel, QLabel]:
            lbl = QLabel(title)
            lbl.setObjectName("statLabel")
            val = QLabel("0")
            val.setObjectName(val_name)
            return lbl, val

        self._stat_total_lbl,   self._stat_total   = _pair("总计", "statValue")
        self._stat_valid_lbl,   self._stat_valid   = _pair("有效", "statValid")
        self._stat_invalid_lbl, self._stat_invalid = _pair("无效", "statInvalid")
        self._stat_unknown_lbl, self._stat_unknown = _pair("未知", "statUnknown")

        for lbl, val in [
            (self._stat_total_lbl,   self._stat_total),
            (self._stat_valid_lbl,   self._stat_valid),
            (self._stat_invalid_lbl, self._stat_invalid),
            (self._stat_unknown_lbl, self._stat_unknown),
        ]:
            row.addWidget(lbl)
            row.addWidget(val)

        row.addStretch()
        return row

    def _build_filter_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("地区:"))
        self._region_filter = QComboBox()
        self._region_filter.setFixedWidth(120)
        self._region_filter.addItem("全部", None)
        self._region_filter.currentIndexChanged.connect(self._on_filter_changed)
        row.addWidget(self._region_filter)
        row.addStretch()
        return row

    def _refresh_region_combo(self):
        current = self._region_filter.currentData()
        self._region_filter.blockSignals(True)
        self._region_filter.clear()
        self._region_filter.addItem("全部", None)
        for r in self._db.get_distinct_regions():
            self._region_filter.addItem(r, r)
        # restore selection if still available
        idx = self._region_filter.findData(current)
        self._region_filter.setCurrentIndex(max(idx, 0))
        self._region_filter.blockSignals(False)

    def _on_filter_changed(self):
        self._page_label.setText("1")
        self._refresh_table()

    def _build_divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    def _build_pagination(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setFixedWidth(32)
        self._page_label = QLabel("1")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setFixedWidth(36)
        self._btn_next = QPushButton("▶")
        self._btn_next.setFixedWidth(32)
        self._page_size_combo = QComboBox()
        for s in [20, 50, 100, 200]:
            self._page_size_combo.addItem(f"{s} 条/页", s)
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        self._page_size_combo.currentIndexChanged.connect(self._refresh_table)
        row.addStretch()
        row.addWidget(self._btn_prev)
        row.addWidget(self._page_label)
        row.addWidget(self._btn_next)
        row.addWidget(self._page_size_combo)
        return row

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self, name: str):
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet(name))
        self._current_theme = name
        self._db.set_config("ui_theme", name)
        self._update_status(self._status_state)
        for action in self._theme_menu.actions():
            action.setChecked(action.text() == name)

    def _on_theme_selected(self, name: str):
        self._apply_theme(name)

    # ── State ────────────────────────────────────────────────────────────────

    def _current_page(self) -> int:
        try:
            return int(self._page_label.text())
        except ValueError:
            return 1

    def _current_page_size(self) -> int:
        return self._page_size_combo.currentData() or 20

    def _refresh_table(self):
        page = self._current_page()
        size = self._current_page_size()
        region = self._region_filter.currentData()
        proxies = self._db.get_all_proxies(page=page, page_size=size, region=region)
        total = self._db.count_proxies(region=region)
        self._model.load(proxies, total, page, size)
        self._rotator.load_proxies(self._db.get_all_proxies(status="valid"))
        cur = self._rotator.get_current()
        self._current_proxy_label.setText(
            f"当前代理: {cur.host}:{cur.port}" if cur else "当前代理: -"
        )
        self._refresh_region_combo()
        self._refresh_stats()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_sub_table()

    def _refresh_sub_table(self) -> None:
        proxies = self._db.get_all_proxies(source="subscription")
        proxies.sort(key=lambda p: (p.type or "", p.host))
        count = len(proxies)
        self._sub_model.load(proxies, count, 1, count or 1)

    def _refresh_stats(self):
        total   = self._db.count_proxies()
        valid   = self._db.count_proxies(status="valid")
        invalid = self._db.count_proxies(status="invalid")
        unknown = total - valid - invalid
        self._stat_total.setText(str(total))
        self._stat_valid.setText(str(valid))
        self._stat_invalid.setText(str(invalid))
        self._stat_unknown.setText(str(max(0, unknown)))

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
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log.append(f"[{timestamp}] {msg}")

    def _update_status(self, state: str):
        self._status_state = state
        port = self._config.listen_port
        colors = THEMES.get(self._current_theme, THEMES[DEFAULT_THEME])
        base = (
            "QStatusBar { background: %s; border-top: 1px solid %s; "
            "font-size: 12px; padding: 0 6px; }"
        ) % (colors["bg"], colors["border"])
        if state == "running":
            self._status_bar.showMessage(
                f"  running   socks5://127.0.0.1:{port}", 0
            )
            text_color = colors["success"]
        elif state == "no_upstream":
            self._status_bar.showMessage(
                f"  warning   socks5://127.0.0.1:{port}  (no upstream)", 0
            )
            text_color = colors["warning"]
        else:
            self._status_bar.showMessage(
                f"  stopped   socks5://127.0.0.1:{port}", 0
            )
            text_color = colors["fg_dim"]
        self._status_bar.setStyleSheet(base + "QStatusBar { color: %s; }" % text_color)

    # ── SOCKS Server ─────────────────────────────────────────────────────────

    def _on_start(self):
        if self._socks_thread and self._socks_thread.isRunning():
            return
        # Load proxies to rotator before starting.
        proxies = self._db.get_all_proxies(status="valid")
        if not proxies:
            QMessageBox.warning(self, "提示", "没有有效代理可用，请先爬取并验证代理")
            return
        self._rotator.load_proxies(proxies)
        self._sync_rotation_mode()
        self._socks_thread = SocksServerThread(self._rotator, self._config.listen_port)
        self._socks_thread.status_changed.connect(self._update_status)
        self._socks_thread.client_connected.connect(
            lambda s: self._log_event(f"[连接] {s}")
        )
        self._socks_thread.proxy_switched.connect(self._on_proxy_switched)
        self._socks_thread.start()
        self._rest_api_thread = RestApiThread(
            self._rotator, self._db, self._config.rest_api_port
        )
        self._rest_api_thread.refresh_requested.connect(self._on_validate)
        self._rest_api_thread.start()
        self._http_proxy_thread = HttpProxyThread(
            self._rotator, self._config.http_proxy_port
        )
        self._http_proxy_thread.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._log_event(
            f"[服务器] SOCKS5: 127.0.0.1:{self._config.listen_port}  "
            f"HTTP: 127.0.0.1:{self._config.http_proxy_port}  "
            f"REST: http://127.0.0.1:{self._config.rest_api_port}  "
            f"代理数: {len(proxies)}"
        )

    def _on_stop(self):
        if self._socks_thread:
            self._socks_thread.stop()
            self._socks_thread.wait(3000)
            self._socks_thread = None
        if self._rest_api_thread:
            self._rest_api_thread.stop()
            self._rest_api_thread = None
        if self._http_proxy_thread:
            self._http_proxy_thread.stop()
            self._http_proxy_thread = None
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._update_status("stopped")
        self._log_event("[服务器] 已关闭")

    def _on_proxy_switched(self, proxy_addr: str):
        self._current_proxy_label.setText(f"当前代理: {proxy_addr}")
        self._log_event(f"[切换] 当前代理: {proxy_addr}")

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
        self._sync_rotation_mode()

    def _sync_rotation_mode(self):
        """Push current mode + params to rotator."""
        idx = self._mode_combo.currentIndex()
        _, mode = _MODE_LABELS[idx]
        params = {}
        if mode == RotationMode.BY_COUNT:
            params["threshold"] = self._param_spin.value()
        elif mode == RotationMode.BY_TIME:
            params["interval_minutes"] = self._param_spin.value()
        elif mode in (RotationMode.BY_SCENE, RotationMode.BY_KEYWORD):
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
        if self._crawler_thread and self._crawler_thread.isRunning():
            self._log_event("[爬取] 爬取正在进行中，请等待完成")
            return
        dlg = AutoCrawlDialog(self)
        if dlg.exec():
            config = dlg.get_config()
            self._db.save_auto_crawl_config(config)
            self._crawler_thread = CrawlerThread(config)
            self._crawler_thread.found.connect(
                lambda n: self._log_event(f"[爬取] 已发现 {n} 个候选代理")
            )
            self._crawler_thread.log.connect(self._log_event)
            self._crawler_thread.finished.connect(self._on_crawl_finished)
            self._crawler_thread.error_occurred.connect(
                lambda e: self._log_event(f"[爬取] 错误: {e}")
            )
            self._crawler_thread.start()
            self._log_event("[爬取] 开始爬取，请稍候...")

    def _on_crawl_finished(self, candidates: list):
        proxies = [
            Proxy(host=c.host, port=c.port, type=c.type,
                  username=c.username, source=c.source)
            for c in candidates
        ]
        self._db.upsert_proxies(proxies)
        self._log_event(f"[爬取] 完成，新增/更新 {len(proxies)} 个代理")
        self._refresh_table()

    def _on_subscription(self):
        if self._subscription_thread and self._subscription_thread.isRunning():
            self._log_event("[订阅] 导入正在进行中，请等待完成")
            return
        dlg = SubscriptionDialog(self)
        if not dlg.exec():
            return
        config = dlg.get_config()
        self._subscription_thread = SubscriptionThread(
            urls=config["urls"],
            concurrency=config["concurrency"],
        )
        self._subscription_thread.log.connect(self._log_event)
        self._subscription_thread.finished.connect(self._on_subscription_finished)
        self._subscription_thread.error_occurred.connect(
            lambda e: self._log_event(f"[订阅] 错误: {e}")
        )
        self._subscription_thread.start()

    def _on_subscription_finished(self, proxies: list):
        self._db.upsert_proxies(proxies)
        self._refresh_table()
        self._refresh_sub_table()

    def _on_validate_pause(self) -> None:
        if self._validator_thread and self._validator_thread.isRunning():
            if self._validator_thread.is_paused:
                self._validator_thread.resume()
                self._set_validator_state("running")
            else:
                self._validator_thread.pause()
                self._set_validator_state("paused")

    def _on_validate_stop(self) -> None:
        if self._validator_thread and self._validator_thread.isRunning():
            self._validator_thread.stop()
        self._set_validator_state("idle")

    def _start_validation(self, proxies: list, label: str) -> None:
        if self._validator_thread and self._validator_thread.isRunning():
            self._log_event("[验证] 验证正在进行中，请等待完成")
            return
        self._val_done = 0
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
        self._validator_thread.regions_ready.connect(self._on_regions_ready)
        self._validator_thread.finished.connect(self._on_validation_finished)
        self._validator_thread.start()
        self._set_validator_state("running")
        self._log_event(label)

    def _on_validate(self):
        all_proxies = self._db.get_all_proxies()
        if not all_proxies:
            QMessageBox.information(self, "提示", "没有可验证的代理")
            return
        self._start_validation(all_proxies, f"[验证] 开始验证 {len(all_proxies)} 个代理")

    def _on_validation_result(self, result: ValidationResult):
        self._db.update_validation(result)
        fields = {
            "status": "valid" if result.success else "invalid",
            "latency": result.latency,
            "anonymity": result.anonymity,
        }
        if result.speed >= 0:
            fields["speed"] = result.speed
        self._model.update_row(result.proxy_id, **fields)
        self._sub_model.update_row(result.proxy_id, **fields)
        self._val_done += 1
        if self._val_done % 10 == 0:
            self._refresh_stats()

    def _on_regions_ready(self, proxy_regions: dict) -> None:
        self._db.batch_update_regions(proxy_regions)
        for proxy_id, region in proxy_regions.items():
            self._model.update_row(proxy_id, region=region)
        self._refresh_stats()

    def _on_validation_finished(self) -> None:
        self._set_validator_state("idle")
        self._refresh_stats()
        self._refresh_table()
        self._log_event("[验证] 完成")

    def _on_toggle_auto_maintenance(self, enabled: bool):
        self._config.auto_maintenance_enabled = enabled
        self._db.set_config("auto_maintenance_enabled", enabled)
        minutes = _AUTO_MAINTENANCE_INTERVAL_MS // 60000
        if enabled:
            self._auto_maintenance_timer.start(_AUTO_MAINTENANCE_INTERVAL_MS)
            self._log_event(f"[自动维护] 已开启，每 {minutes} 分钟验证一次并自动清理/补充代理")
        else:
            self._auto_maintenance_timer.stop()
            self._log_event("[自动维护] 已关闭")

    def _on_auto_maintenance_tick(self):
        if self._validator_thread and self._validator_thread.isRunning():
            self._log_event("[自动维护] 上一轮验证尚未完成，本轮跳过")
            return
        if self._crawler_thread and self._crawler_thread.isRunning():
            self._log_event("[自动维护] 爬取正在进行中，本轮跳过")
            return
        all_proxies = self._db.get_all_proxies()
        if not all_proxies:
            self._log_event("[自动维护] 代理池为空，本轮跳过")
            return
        self._log_event(f"[自动维护] 开始定时验证 {len(all_proxies)} 个代理")
        self._start_validation(all_proxies, f"[验证] 开始验证 {len(all_proxies)} 个代理")
        # Guards above confirmed the validator was idle, so _start_validation
        # is guaranteed to have created a fresh thread rather than skipping.
        if self._validator_thread:
            self._validator_thread.finished.connect(self._on_auto_maintenance_validation_done)

    def _on_auto_maintenance_validation_done(self):
        invalid = [p for p in self._db.get_all_proxies() if p.status == "invalid"]
        if invalid:
            self._db.delete_proxies([p.id for p in invalid])
            self._log_event(f"[自动维护] 已删除 {len(invalid)} 个失效代理")
            self._refresh_table()

        valid_count = self._db.count_proxies(status="valid")
        if valid_count >= _AUTO_REPLENISH_VALID_THRESHOLD:
            self._log_event(f"[自动维护] 当前有效代理 {valid_count} 个，无需补充，本轮结束")
            return

        config = self._db.load_auto_crawl_config()
        if not config:
            self._log_event("[自动维护] 尚未配置过自动爬取来源，跳过补充（可先手动打开一次'自动爬取'对话框并确认配置）")
            return

        capped_config = {
            "fofa": {**config.get("fofa", {}),
                     "limit": min(config.get("fofa", {}).get("limit", 0), _AUTO_REPLENISH_CRAWL_LIMIT)},
            "free": {**config.get("free", {}),
                     "limit": min(config.get("free", {}).get("limit", 0), _AUTO_REPLENISH_CRAWL_LIMIT)},
        }

        self._crawler_thread = CrawlerThread(capped_config)
        self._crawler_thread.found.connect(
            lambda n: self._log_event(f"[爬取] 已发现 {n} 个候选代理")
        )
        self._crawler_thread.log.connect(self._log_event)
        self._crawler_thread.finished.connect(self._on_crawl_finished)
        self._crawler_thread.finished.connect(lambda: self._log_event("[自动维护] 本轮完成"))
        self._crawler_thread.error_occurred.connect(
            lambda e: self._log_event(f"[爬取] 错误: {e}")
        )
        self._crawler_thread.start()
        self._log_event(
            f"[自动维护] 有效代理仅 {valid_count} 个，开始补充爬取（单次上限 {_AUTO_REPLENISH_CRAWL_LIMIT}）..."
        )

    def _on_speed_test(self):
        valid_proxies = self._db.get_all_proxies(status="valid")
        if not valid_proxies:
            QMessageBox.information(self, "提示", "没有有效代理可测速")
            return
        self._start_speed_test(valid_proxies, f"[测速] 开始测速 {len(valid_proxies)} 个代理")

    def _on_speed_pause(self) -> None:
        if self._speed_thread and self._speed_thread.isRunning():
            if self._speed_thread.is_paused:
                self._speed_thread.resume()
                self._set_speed_state("running")
            else:
                self._speed_thread.pause()
                self._set_speed_state("paused")

    def _on_speed_stop(self) -> None:
        if self._speed_thread and self._speed_thread.isRunning():
            self._speed_thread.stop()
        self._set_speed_state("idle")

    def _speed_test_selected(self, proxy_ids: list[int]):
        if not proxy_ids:
            return
        id_set = set(proxy_ids)
        proxies = [p for p in self._db.get_all_proxies() if p.id in id_set]
        if not proxies:
            return
        self._start_speed_test(proxies, f"[测速] 开始测速选中 {len(proxies)} 个代理")

    def _start_speed_test(self, proxies: list, label: str) -> None:
        if self._speed_thread and self._speed_thread.isRunning():
            self._log_event("[测速] 测速正在进行中，请等待完成")
            return
        from app.core.speed_test import SpeedTestThread
        self._speed_thread = SpeedTestThread(
            proxies=proxies,
            concurrency=min(20, self._config.validator_concurrency),
        )
        self._speed_thread.result_ready.connect(self._on_speed_result)
        self._speed_thread.progress.connect(
            lambda done, total: self._log_event(f"[测速] {done}/{total}")
        )
        self._speed_thread.finished.connect(self._on_speed_finished)
        self._speed_thread.start()
        self._set_speed_state("running")
        self._log_event(label)

    def _on_speed_result(self, proxy_id: int, speed_kbps: float):
        if speed_kbps >= 0:
            self._db.update_speed(proxy_id, speed_kbps)
            self._model.update_row(proxy_id, speed=speed_kbps)
            self._sub_model.update_row(proxy_id, speed=speed_kbps)

    def _on_speed_finished(self):
        self._set_speed_state("idle")
        self._refresh_table()
        self._log_event("[测速] 完成")

    def _selected_proxy_ids(self) -> list[int]:
        selected_rows = sorted(set(i.row() for i in self._table.selectedIndexes()))
        return [
            p.id for row in selected_rows
            if (p := self._model.get_proxy(row)) is not None
        ]

    def _on_table_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        # Right-clicking outside the current selection re-targets it to the
        # clicked row, matching standard table/list context-menu behavior.
        if not self._table.selectionModel().isRowSelected(index.row(), index.parent()):
            self._table.selectRow(index.row())

        selected_ids = self._selected_proxy_ids()
        if not selected_ids:
            return

        menu = QMenu(self)
        delete_act = menu.addAction(f"删除代理 ({len(selected_ids)})")
        validate_act = menu.addAction("重新验证")
        speed_act = menu.addAction("速度测试")
        menu.addSeparator()
        copy_act = menu.addAction("复制代理地址")

        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen is delete_act:
            self._delete_selected(selected_ids)
        elif chosen is validate_act:
            self._validate_selected(selected_ids)
        elif chosen is speed_act:
            self._speed_test_selected(selected_ids)
        elif chosen is copy_act:
            self._copy_selected_addresses(selected_ids)

    def _selected_sub_proxy_ids(self) -> list[int]:
        selected_rows = sorted(set(i.row() for i in self._sub_table.selectedIndexes()))
        return [
            p.id for row in selected_rows
            if (p := self._sub_model.get_proxy(row)) is not None
        ]

    def _on_sub_table_context_menu(self, pos):
        index = self._sub_table.indexAt(pos)
        if not index.isValid():
            return
        if not self._sub_table.selectionModel().isRowSelected(index.row(), index.parent()):
            self._sub_table.selectRow(index.row())

        selected_ids = self._selected_sub_proxy_ids()
        if not selected_ids:
            return

        menu = QMenu(self)
        delete_act = menu.addAction(f"删除代理 ({len(selected_ids)})")
        validate_act = menu.addAction("重新验证")
        speed_act = menu.addAction("速度测试")
        menu.addSeparator()
        copy_act = menu.addAction("复制代理地址")

        chosen = menu.exec(self._sub_table.viewport().mapToGlobal(pos))
        if chosen is delete_act:
            self._delete_selected(selected_ids)
            self._refresh_sub_table()
        elif chosen is validate_act:
            self._validate_selected(selected_ids)
        elif chosen is speed_act:
            self._speed_test_selected(selected_ids)
        elif chosen is copy_act:
            self._copy_selected_addresses(selected_ids)

    def _copy_selected_addresses(self, proxy_ids: list[int]):
        id_set = set(proxy_ids)
        proxies = [p for p in self._db.get_all_proxies() if p.id in id_set]
        if not proxies:
            return
        text = "\n".join(p.url for p in proxies)
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
        self._log_event(f"[管理] 已复制 {len(proxies)} 个代理地址到剪贴板")

    def _on_batch_manage(self):
        selected_ids = self._selected_proxy_ids()
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
        self._start_validation(proxies, f"[验证] 开始验证选中 {len(proxies)} 个代理")

    def _on_export(self):
        proxies = self._db.get_all_proxies()
        dlg = ExportDialog(proxies, self)
        dlg.exec()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._auto_maintenance_timer.stop()
        self._on_stop()
        for thread in (self._socks_thread, self._rest_api_thread, self._http_proxy_thread,
                       self._crawler_thread, self._validator_thread, self._speed_thread,
                       self._subscription_thread):
            if thread and thread.isRunning():
                thread.stop() if hasattr(thread, "stop") else None
                thread.wait(3000)
        self._db.close()
        event.accept()
