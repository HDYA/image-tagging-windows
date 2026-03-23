"""
媒体文件智能分类系统 - 智能类别选择器

功能:
    - 推荐结果置顶 (来自文件名标注/人脸识别)
    - 多模式搜索: 中文/拼音全拼/首字母缩写/英文数字
"""
from typing import Optional

from PySide6.QtCore import Qt, Signal, QSortFilterProxyModel, QModelIndex
from PySide6.QtGui import QStandardItemModel, QStandardItem, QColor, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QListView,
    QLabel, QComboBox, QCompleter, QStyledItemDelegate, QStyle,
    QApplication
)

from core.models import CategoryNode

try:
    from pypinyin import lazy_pinyin, pinyin, Style
    _HAS_PYPINYIN = True
except ImportError:
    _HAS_PYPINYIN = False


def _to_pinyin_full(text: str) -> str:
    if not _HAS_PYPINYIN:
        return ""
    return ''.join(lazy_pinyin(text))


def _to_pinyin_initials(text: str) -> str:
    if not _HAS_PYPINYIN:
        return ""
    return ''.join(p[0] for p in pinyin(text, style=Style.FIRST_LETTER))


ROLE_CAT_ID = Qt.UserRole + 1
ROLE_CAT_PATH = Qt.UserRole + 2
ROLE_SEARCH_TEXT = Qt.UserRole + 3
ROLE_PINYIN_FULL = Qt.UserRole + 4
ROLE_PINYIN_INITIALS = Qt.UserRole + 5
ROLE_IS_RECOMMENDED = Qt.UserRole + 6
ROLE_SORT_PRIORITY = Qt.UserRole + 7


class CategoryFilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self.setDynamicSortFilter(True)

    def set_search(self, text: str):
        self._search_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._search_text:
            return True
        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        if model.data(idx, ROLE_IS_RECOMMENDED):
            return True
        search = self._search_text
        search_blob = model.data(idx, ROLE_SEARCH_TEXT) or ""
        if search in search_blob:
            return True
        py_full = model.data(idx, ROLE_PINYIN_FULL) or ""
        if search in py_full:
            return True
        py_initials = model.data(idx, ROLE_PINYIN_INITIALS) or ""
        if search in py_initials:
            return True
        return False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        l_prio = self.sourceModel().data(left, ROLE_SORT_PRIORITY) or 1
        r_prio = self.sourceModel().data(right, ROLE_SORT_PRIORITY) or 1
        if l_prio != r_prio:
            return l_prio < r_prio
        l_path = self.sourceModel().data(left, ROLE_CAT_PATH) or ""
        r_path = self.sourceModel().data(right, ROLE_CAT_PATH) or ""
        return l_path < r_path


class CategoryItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        is_rec = index.data(ROLE_IS_RECOMMENDED)
        if is_rec:
            option.font.setBold(True)
            if not option.text.startswith("⭐"):
                option.text = "⭐ " + option.text


class SmartCategorySelector(QWidget):
    category_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._categories: list[CategoryNode] = []
        self._recommended_ids: set[int] = set()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索: 中文/拼音全拼/首字母/英文数字...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_edit)
        self.list_view = QListView()
        self.list_view.setItemDelegate(CategoryItemDelegate(self.list_view))
        self.list_view.setAlternatingRowColors(True)
        self.list_view.clicked.connect(self._on_item_clicked)
        self._source_model = QStandardItemModel()
        self._filter_model = CategoryFilterModel()
        self._filter_model.setSourceModel(self._source_model)
        self._filter_model.setSortRole(ROLE_SORT_PRIORITY)
        self.list_view.setModel(self._filter_model)
        layout.addWidget(self.list_view, 1)
        self.selection_label = QLabel("未选择")
        self.selection_label.setStyleSheet("font-size: 11px; color: #666; padding: 2px;")
        layout.addWidget(self.selection_label)

    def set_categories(self, categories: list[CategoryNode]):
        self._categories = categories
        self._rebuild_model()

    def set_recommended_ids(self, cat_ids: set[int]):
        self._recommended_ids = cat_ids
        self._rebuild_model()

    def set_recommended_from_results(self, candidates: list[CategoryNode]):
        self._recommended_ids = {c.id for c in candidates}
        self._rebuild_model()

    def selected_category_id(self) -> Optional[int]:
        indexes = self.list_view.selectionModel().selectedIndexes()
        if indexes:
            idx = self._filter_model.mapToSource(indexes[0])
            return self._source_model.data(idx, ROLE_CAT_ID)
        return None

    def select_category_id(self, cat_id: int):
        for row in range(self._filter_model.rowCount()):
            idx = self._filter_model.index(row, 0)
            source_idx = self._filter_model.mapToSource(idx)
            if self._source_model.data(source_idx, ROLE_CAT_ID) == cat_id:
                self.list_view.setCurrentIndex(idx)
                self._update_selection_label(cat_id)
                return

    def clear_search(self):
        self.search_edit.clear()

    def _rebuild_model(self):
        self._source_model.clear()
        for cat in self._categories:
            is_rec = cat.id in self._recommended_ids
            display = f"{cat.path}  [{cat.pinyin_abbr}]"
            item = QStandardItem(display)
            search_blob = f"{cat.path} {cat.leaf_name} {cat.pinyin_full} {cat.pinyin_abbr}".lower()
            path_parts = cat.path.split('/')
            for part in path_parts:
                search_blob += f" {_to_pinyin_full(part)} {_to_pinyin_initials(part)}"
            search_blob = search_blob.lower()
            item.setData(cat.id, ROLE_CAT_ID)
            item.setData(cat.path, ROLE_CAT_PATH)
            item.setData(search_blob, ROLE_SEARCH_TEXT)
            item.setData(cat.pinyin_full.lower(), ROLE_PINYIN_FULL)
            item.setData(cat.pinyin_abbr.lower(), ROLE_PINYIN_INITIALS)
            item.setData(is_rec, ROLE_IS_RECOMMENDED)
            item.setData(0 if is_rec else 1, ROLE_SORT_PRIORITY)
            if is_rec:
                item.setBackground(QBrush(QColor(255, 253, 230)))
            self._source_model.appendRow(item)
        self._filter_model.sort(0)
        if self._recommended_ids and self._filter_model.rowCount() > 0:
            self.list_view.setCurrentIndex(self._filter_model.index(0, 0))
            first_id = self._filter_model.data(self._filter_model.index(0, 0), ROLE_CAT_ID)
            if first_id:
                self._update_selection_label(first_id)

    def _on_search_changed(self, text: str):
        self._filter_model.set_search(text)
        if self._filter_model.rowCount() > 0:
            self.list_view.setCurrentIndex(self._filter_model.index(0, 0))

    def _on_item_clicked(self, index: QModelIndex):
        source_idx = self._filter_model.mapToSource(index)
        cat_id = self._source_model.data(source_idx, ROLE_CAT_ID)
        if cat_id is not None:
            self._update_selection_label(cat_id)
            self.category_selected.emit(cat_id)

    def _update_selection_label(self, cat_id: int):
        for cat in self._categories:
            if cat.id == cat_id:
                self.selection_label.setText(f"已选: {cat.path}")
                self.selection_label.setStyleSheet(
                    "font-size: 11px; color: #1976D2; font-weight: bold; padding: 2px;")
                return
