"""
媒体文件智能分类系统 - 分组列表面板
"""
from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QLabel
)

from core.models import MediaGroup


STATUS_COLORS = {
    "auto": QColor(200, 255, 200),
    "confirmed": QColor(180, 240, 180),
    "conflict": QColor(255, 220, 200),
    "confirm": QColor(255, 255, 200),
    "pending": QColor(240, 240, 240),
    "skipped": QColor(220, 220, 220),
}

STATUS_LABELS = {
    "auto": "✅ 自动",
    "confirmed": "✅ 已确认",
    "conflict": "⚠️ 冲突",
    "confirm": "🔍 待确认",
    "pending": "⏳ 待处理",
    "skipped": "⏭ 跳过",
}


class GroupPanel(QWidget):
    group_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[MediaGroup] = []
        self._filtered: list[MediaGroup] = []
        self._filter_status: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("分组列表")
        self.title_label.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(self.title_label)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["组号", "时间", "文件数", "标注", "分类", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(5, 100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #1976D2; color: #fff; }"
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

    def load_groups(self, groups: list[MediaGroup]):
        self._groups = groups
        self._apply_filter()

    def set_filter(self, status: Optional[str]):
        self._filter_status = status
        self._apply_filter()

    def _apply_filter(self):
        if self._filter_status:
            self._filtered = [g for g in self._groups if g.status == self._filter_status]
        else:
            self._filtered = list(self._groups)
        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(len(self._filtered))
        for row, group in enumerate(self._filtered):
            color = STATUS_COLORS.get(group.status, QColor(255, 255, 255))
            brush = QBrush(color)
            items = [str(group.id), group.time_span_str, str(group.file_count),
                     group.detected_tag or "", group.category_path or "",
                     STATUS_LABELS.get(group.status, group.status)]
            fg_brush = QBrush(QColor(0, 0, 0))
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setBackground(brush)
                item.setForeground(fg_brush)
                item.setData(Qt.UserRole, group.id)
                self.table.setItem(row, col, item)
        count_text = f"分组列表 ({len(self._filtered)}"
        if self._filter_status:
            count_text += f" / {len(self._groups)} 总计"
        count_text += ")"
        self.title_label.setText(count_text)

    def _on_selection_changed(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            row = rows[0].row()
            item = self.table.item(row, 0)
            if item:
                group_id = item.data(Qt.UserRole)
                self.group_selected.emit(group_id)

    def select_next_pending(self):
        current_row = self.table.currentRow()
        for i in range(current_row + 1, self.table.rowCount()):
            group = self._filtered[i]
            if group.status in ("pending", "conflict", "confirm"):
                self.table.selectRow(i)
                self.table.scrollTo(self.table.model().index(i, 0))
                return
        for i in range(0, min(current_row + 1, self.table.rowCount())):
            group = self._filtered[i]
            if group.status in ("pending", "conflict", "confirm"):
                self.table.selectRow(i)
                self.table.scrollTo(self.table.model().index(i, 0))
                return
