from __future__ import annotations
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from app.db.models import Proxy

COLUMNS = ["#", "Host", "Port", "类型", "地区", "延时(ms)", "状态", "匿名性", "操作"]
_STATUS_DISPLAY = {"valid": "✓ 有效", "invalid": "✗ 无效", "unknown": "? 未知"}
_ANON_DISPLAY = {"high": "高匿", "medium": "匿名", "transparent": "透明", "": "-"}


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
                p.host, p.port, p.type, p.region or "-",
                f"{p.latency:.0f}" if p.latency >= 0 else "-",
                _STATUS_DISPLAY.get(p.status, p.status),
                _ANON_DISPLAY.get(p.anonymity, p.anonymity or "-"),
                "",  # 操作列由 delegate 处理
            ]
            return str(values[col])
        if role == Qt.ItemDataRole.UserRole:
            return p  # 返回完整 Proxy 对象
        return None

    def get_proxy(self, row: int) -> Proxy | None:
        if 0 <= row < len(self._proxies):
            return self._proxies[row]
        return None

    @property
    def total_count(self) -> int:
        return self._total
