"""
媒体文件智能分类系统 - 类别树面板
"""
from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QHBoxLayout
)

from core.models import CategoryNode


class CategoryPanel(QWidget):
    category_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._categories: list[CategoryNode] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel("📁 类别树")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索类别...")
        self.search_edit.textChanged.connect(self._on_search)
        layout.addWidget(self.search_edit)
        self.stats_label = QLabel("0 个类别")
        self.stats_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.stats_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["类别", "拼音", "缩写"])
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 50)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

    def load_categories(self, categories: list[CategoryNode]):
        self._categories = categories
        self.tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for cat in sorted(categories, key=lambda c: c.path):
            parts = cat.path.split('/')
            parent_path = '/'.join(parts[:-1]) if len(parts) > 1 else None
            item = QTreeWidgetItem()
            item.setText(0, parts[-1])
            item.setText(1, cat.pinyin_full)
            item.setText(2, cat.pinyin_abbr)
            item.setData(0, Qt.UserRole, cat.path)
            item.setData(0, Qt.UserRole + 1, cat.id)
            if parent_path and parent_path in items:
                items[parent_path].addChild(item)
            else:
                if parent_path:
                    self._ensure_parents(items, parent_path)
                    if parent_path in items:
                        items[parent_path].addChild(item)
                    else:
                        self.tree.addTopLevelItem(item)
                else:
                    self.tree.addTopLevelItem(item)
            items[cat.path] = item
        self.tree.expandAll()
        self.stats_label.setText(f"{len(categories)} 个类别")

    def _ensure_parents(self, items: dict, path: str):
        parts = path.split('/')
        for i in range(len(parts)):
            partial = '/'.join(parts[:i + 1])
            if partial not in items:
                item = QTreeWidgetItem()
                item.setText(0, parts[i])
                item.setData(0, Qt.UserRole, partial)
                parent_path = '/'.join(parts[:i]) if i > 0 else None
                if parent_path and parent_path in items:
                    items[parent_path].addChild(item)
                else:
                    self.tree.addTopLevelItem(item)
                items[partial] = item

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        path = item.data(0, Qt.UserRole)
        if path:
            self.category_selected.emit(path)

    def _on_search(self, text: str):
        text = text.lower().strip()
        iterator = self.tree.invisibleRootItem()
        self._set_visible_recursive(iterator, text)

    def _set_visible_recursive(self, item: QTreeWidgetItem, search: str) -> bool:
        visible = False
        for i in range(item.childCount()):
            child = item.child(i)
            child_visible = self._set_visible_recursive(child, search)
            if not search:
                child.setHidden(False)
                visible = True
            elif search in (child.text(0) + child.text(1) + child.text(2)).lower():
                child.setHidden(False)
                visible = True
            elif child_visible:
                child.setHidden(False)
                visible = True
            else:
                child.setHidden(True)
        return visible
