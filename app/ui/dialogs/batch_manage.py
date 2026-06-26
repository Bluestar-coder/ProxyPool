from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QDialogButtonBox,
)
from PyQt6.QtCore import pyqtSignal


class BatchManageDialog(QDialog):
    delete_selected = pyqtSignal()
    delete_invalid = pyqtSignal()
    reset_status = pyqtSignal()
    validate_selected = pyqtSignal()

    def __init__(self, selected_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量管理")
        self._label = QLabel(f"已选中 {selected_count} 个代理")

        btn_del_sel = QPushButton("删除选中")
        btn_del_inv = QPushButton("删除所有无效")
        btn_reset = QPushButton("重置状态为未知")
        btn_validate = QPushButton("验证选中")

        btn_del_sel.clicked.connect(lambda: (self.delete_selected.emit(), self.accept()))
        btn_del_inv.clicked.connect(lambda: (self.delete_invalid.emit(), self.accept()))
        btn_reset.clicked.connect(lambda: (self.reset_status.emit(), self.accept()))
        btn_validate.clicked.connect(lambda: (self.validate_selected.emit(), self.accept()))

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        for btn in [btn_del_sel, btn_del_inv, btn_reset, btn_validate]:
            layout.addWidget(btn)
        layout.addWidget(close)
