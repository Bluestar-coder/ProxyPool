from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.db.models import Proxy

COLUMNS = ["#", "Host", "Port", "类型", "地区", "延时(ms)", "速度(KB/s)", "状态", "匿名性", "操作"]
_STATUS_DISPLAY = {"valid": "✓ 有效", "invalid": "✗ 无效", "unknown": "? 未知"}
_ANON_DISPLAY = {"high": "高匿", "medium": "匿名", "transparent": "透明", "": "-"}
# Columns that should be centered
_CENTER_COLS = {0, 2, 3, 5, 6, 7, 8}  # #, Port, 类型, 延时, 速度, 状态, 匿名性


class ProxyTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxies: list[Proxy] = []
        self._page = 1
        self._page_size = 10
        self._total = 0

    def load(self, proxies: list[Proxy], total: int, page: int, page_size: int):
        self.beginResetModel()
        self._proxies = proxies
        self._total = total
        self._page = page
        self._page_size = page_size
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._proxies)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._proxies[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            offset = (self._page - 1) * self._page_size
            values = [
                offset + index.row() + 1,
                p.host,
                p.port,
                p.type,
                p.region or "-",
                f"{p.latency:.0f}" if p.latency is not None and p.latency >= 0 else "-",
                f"{p.speed:.0f}" if p.speed is not None and p.speed >= 0 else "-",
                _STATUS_DISPLAY.get(p.status, p.status),
                _ANON_DISPLAY.get(p.anonymity, p.anonymity or "-"),
                "",  # 操作列由 delegate 处理
            ]
            return str(values[col])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in _CENTER_COLS:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.UserRole:
            return p  # 返回完整 Proxy 对象
        return None

    def get_proxy(self, row: int) -> Proxy | None:
        if 0 <= row < len(self._proxies):
            return self._proxies[row]
        return None

    def update_row(self, proxy_id: int, **fields) -> bool:
        """Update proxy fields in-place and notify view. Returns True if found on current page."""
        for row, proxy in enumerate(self._proxies):
            if proxy.id == proxy_id:
                for key, value in fields.items():
                    setattr(proxy, key, value)
                top_left = self.index(row, 0)
                bottom_right = self.index(row, len(COLUMNS) - 1)
                self.dataChanged.emit(top_left, bottom_right)
                return True
        return False

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sort by column."""
        if not self._proxies:
            return
        reverse = order == Qt.SortOrder.DescendingOrder
        # Untested (-1) values should always sink to the bottom of the view,
        # regardless of sort direction, so the sentinel flips with `reverse`
        # rather than always meaning "smallest" or "largest".
        untested = float("-inf") if reverse else float("inf")
        key_funcs = {
            0: lambda p: p.id,
            1: lambda p: p.host,
            2: lambda p: p.port,
            3: lambda p: p.type,
            4: lambda p: p.region or "",
            5: lambda p: p.latency if p.latency is not None and p.latency >= 0 else untested,
            6: lambda p: p.speed if p.speed is not None and p.speed >= 0 else untested,
            7: lambda p: 0 if p.status == "valid" else 1 if p.status == "invalid" else 2,
            8: lambda p: p.anonymity or "",
        }
        if column in key_funcs:
            self.beginResetModel()
            self._proxies.sort(key=key_funcs[column], reverse=reverse)
            self.endResetModel()

    @property
    def total_count(self) -> int:
        return self._total
