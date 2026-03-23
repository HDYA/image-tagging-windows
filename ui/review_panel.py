"""
媒体文件智能分类系统 - 审核面板 (缩略图 + 全窗口预览 + 文件级分类覆盖)
"""
import os
from typing import Optional
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QPixmap, QImage, QKeySequence, QShortcut, QPainter, QMovie
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QGroupBox, QGridLayout,
    QSizePolicy, QCompleter, QDialog, QToolButton, QStyle,
    QApplication, QLineEdit
)

from core.models import MediaFile, MediaGroup, CategoryNode
from .category_selector import SmartCategorySelector

THUMB_SIZE = QSize(180, 140)


class ImagePreviewDialog(QDialog):
    file_override_requested = Signal(int, str)

    def __init__(self, files: list[MediaFile], start_index: int = 0, parent=None):
        super().__init__(parent)
        self._files = files
        self._index = start_index
        self.setWindowTitle("预览")
        self.setWindowFlags(Qt.Dialog | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumSize(800, 600)
        if parent:
            self.resize(parent.window().size())
        else:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.resize(int(geo.width() * 0.9), int(geo.height() * 0.9))
        self._setup_ui()
        self._setup_shortcuts()
        self._show_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #1a1a1a;")
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setMinimumHeight(400)
        layout.addWidget(self.image_label, 1)
        bottom = QWidget()
        bottom.setStyleSheet("background: #2d2d2d; color: white; padding: 8px;")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 6, 12, 6)
        self.btn_prev = QPushButton("◀ 上一张 (A)")
        self.btn_prev.setStyleSheet("color: white; background: #555; border: none; padding: 6px 12px;")
        self.btn_prev.clicked.connect(self._go_prev)
        bottom_layout.addWidget(self.btn_prev)
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("color: #ddd; font-size: 13px;")
        self.info_label.setWordWrap(True)
        bottom_layout.addWidget(self.info_label, 1)
        self.btn_override = QPushButton("🏷 修改此文件分类")
        self.btn_override.setStyleSheet("color: white; background: #E65100; border: none; padding: 6px 12px; font-weight: bold;")
        self.btn_override.clicked.connect(self._request_override)
        bottom_layout.addWidget(self.btn_override)
        self.btn_next = QPushButton("下一张 (D) ▶")
        self.btn_next.setStyleSheet("color: white; background: #555; border: none; padding: 6px 12px;")
        self.btn_next.clicked.connect(self._go_next)
        bottom_layout.addWidget(self.btn_next)
        layout.addWidget(bottom)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Left), self, self._go_prev)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._go_next)
        QShortcut(QKeySequence(Qt.Key_A), self, self._go_prev)
        QShortcut(QKeySequence(Qt.Key_D), self, self._go_next)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.close)
        QShortcut(QKeySequence(Qt.Key_Space), self, self._go_next)

    def _go_prev(self):
        if self._index > 0:
            self._index -= 1
            self._show_current()

    def _go_next(self):
        if self._index < len(self._files) - 1:
            self._index += 1
            self._show_current()

    def _show_current(self):
        f = self._files[self._index]
        self.btn_prev.setEnabled(self._index > 0)
        self.btn_next.setEnabled(self._index < len(self._files) - 1)
        ext = Path(f.path).suffix.lower()
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v', '.3gp', '.webm'}
        if ext in video_exts:
            self.image_label.setText(f"🎬 视频文件\n\n{f.filename}\n\n(双击用系统播放器打开)")
            self.image_label.setStyleSheet("background: #1a1a1a; color: white; font-size: 18px;")
            self.image_label.mousePressEvent = lambda e: self._open_external(f.path)
        else:
            pixmap = QPixmap(f.path)
            if pixmap.isNull():
                self.image_label.setText(f"❌ 无法加载\n{f.filename}")
                self.image_label.setStyleSheet("background: #1a1a1a; color: #ff6666; font-size: 16px;")
            else:
                label_size = self.image_label.size()
                scaled = pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                self.image_label.setStyleSheet("background: #1a1a1a;")
        info_parts = [f"<b>{f.filename}</b>"]
        info_parts.append(f"({self._index + 1} / {len(self._files)})")
        if f.timestamp:
            info_parts.append(f.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        if f.timestamp_source:
            info_parts.append(f"[{f.timestamp_source}]")
        if f.file_tag:
            info_parts.append(f"标注: <code>{f.file_tag}</code>")
        if f.has_override:
            info_parts.append(f"<span style='color: #FF9800; font-weight: bold;'>⚡ 文件分类覆盖: {f.file_category_path}</span>")
        self.info_label.setText("  |  ".join(info_parts))

    def _request_override(self):
        self.file_override_requested.emit(self._index, self._files[self._index].path)

    def _open_external(self, filepath: str):
        import subprocess
        try:
            if os.name == 'nt':
                os.startfile(filepath)
            else:
                subprocess.Popen(['xdg-open', filepath])
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(50, self._show_current)


class FileOverrideDialog(QDialog):
    def __init__(self, file: MediaFile, categories: list[CategoryNode],
                 current_group_category_path: str = "",
                 recommended_ids: set[int] = None, parent=None):
        super().__init__(parent)
        self._file = file
        self._categories = categories
        self.setWindowTitle(f"修改文件分类 — {file.filename}")
        self.setMinimumSize(550, 450)
        self._setup_ui(current_group_category_path, recommended_ids or set())

    def _setup_ui(self, group_cat_path: str, recommended_ids: set[int]):
        layout = QVBoxLayout(self)
        info = QLabel(f"<b>文件:</b> {self._file.filename}<br>"
                      f"<b>组级分类:</b> {group_cat_path or '(无)'}<br>"
                      f"<b>当前覆盖:</b> {self._file.file_category_path or '(无，跟随组)'}")
        info.setWordWrap(True)
        info.setStyleSheet("padding: 8px; background: #f5f5f5; border-radius: 4px;")
        layout.addWidget(info)
        self.btn_follow_group = QPushButton(
            f"↩ 跟随组分类 ({group_cat_path})" if group_cat_path else "↩ 跟随组分类 (清除覆盖)")
        self.btn_follow_group.setStyleSheet("padding: 6px; margin: 4px 0;")
        self.btn_follow_group.clicked.connect(self._on_follow_group)
        layout.addWidget(self.btn_follow_group)
        layout.addWidget(QLabel("或选择新分类:"))
        self.selector = SmartCategorySelector()
        self.selector.set_categories(self._categories)
        self.selector.set_recommended_ids(recommended_ids)
        if self._file.file_category_id:
            self.selector.select_category_id(self._file.file_category_id)
        layout.addWidget(self.selector, 1)
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("✅ 确定")
        btn_ok.setStyleSheet("background: #4CAF50; color: white; padding: 8px 20px; font-weight: bold;")
        btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("padding: 8px 20px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        self._result_id = self._file.file_category_id
        self._follow_group = False

    def _on_follow_group(self):
        self._follow_group = True
        self.accept()

    def _on_ok(self):
        self._follow_group = False
        self._result_id = self.selector.selected_category_id()
        self.accept()

    def get_selected_category_id(self) -> Optional[int]:
        if self._follow_group:
            return None
        return self._result_id


class ThumbnailWidget(QLabel):
    clicked = Signal(int)

    def __init__(self, file: MediaFile, index: int, parent=None):
        super().__init__(parent)
        self._file = file
        self._index = index
        self.setFixedSize(THUMB_SIZE)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameStyle(QFrame.Box)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        self._load_thumbnail()

    def _update_style(self):
        if self._file.has_override:
            self.setStyleSheet("border: 3px solid #FF9800; background: #f0f0f0;")
        else:
            self.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")

    def _load_thumbnail(self):
        ext = Path(self._file.path).suffix.lower()
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.m4v', '.3gp', '.webm'}
        if ext in video_exts:
            self.setText(f"🎬\n{self._file.filename[:20]}")
            base = "border: 3px solid #FF9800;" if self._file.has_override else "border: 1px solid #ccc;"
            self.setStyleSheet(f"{base} background: #333; color: white; font-size: 11px;")
            return
        try:
            pixmap = QPixmap(self._file.path)
            if pixmap.isNull():
                self.setText(f"❌\n{self._file.filename[:20]}")
                return
            scaled = pixmap.scaled(THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.setPixmap(scaled)
        except Exception:
            self.setText(f"⚠\n{self._file.filename[:20]}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)


class ReviewPanel(QWidget):
    classification_confirmed = Signal(int, int)
    group_skipped = Signal(int)
    file_category_changed = Signal(int, object)
    next_pending_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_group_id: Optional[int] = None
        self._current_group: Optional[MediaGroup] = None
        self._files: list[MediaFile] = []
        self._categories: list[CategoryNode] = []
        self._recommended_ids: set[int] = set()
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.info_label = QLabel("选择一个分组进行审核")
        self.info_label.setStyleSheet("font-size: 13px; padding: 4px; background: #f5f5f5; color: #333; border-radius: 4px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        thumb_scroll = QScrollArea()
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setFixedHeight(THUMB_SIZE.height() + 60)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumb_container = QWidget()
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setContentsMargins(4, 4, 4, 4)
        self.thumb_layout.setSpacing(6)
        self.thumb_layout.addStretch()
        thumb_scroll.setWidget(self.thumb_container)
        layout.addWidget(thumb_scroll)
        classify_layout = QHBoxLayout()
        self.category_selector = SmartCategorySelector()
        self.category_selector.setMaximumHeight(200)
        classify_layout.addWidget(self.category_selector, 1)
        btn_col = QVBoxLayout()
        self.btn_confirm = QPushButton("✅ 确认全组\n(Enter)")
        self.btn_confirm.setStyleSheet("background: #4CAF50; color: white; padding: 12px 16px; font-weight: bold; font-size: 13px;")
        self.btn_confirm.setMinimumHeight(50)
        self.btn_confirm.clicked.connect(self._on_confirm)
        btn_col.addWidget(self.btn_confirm)
        self.btn_skip = QPushButton("⏭ 跳过\n(Esc)")
        self.btn_skip.setStyleSheet("padding: 12px 16px; font-size: 12px;")
        self.btn_skip.setMinimumHeight(40)
        self.btn_skip.clicked.connect(self._on_skip)
        btn_col.addWidget(self.btn_skip)
        self.btn_next_pending = QPushButton("⏩ 下一个未分类\n(Tab)")
        self.btn_next_pending.setStyleSheet("background: #1976D2; color: white; padding: 8px 16px; font-size: 11px;")
        self.btn_next_pending.setMinimumHeight(36)
        self.btn_next_pending.clicked.connect(self._on_next_pending)
        btn_col.addWidget(self.btn_next_pending)
        btn_col.addStretch()
        classify_layout.addLayout(btn_col)
        layout.addLayout(classify_layout, 1)
        self.override_label = QLabel("")
        self.override_label.setStyleSheet("color: #E65100; font-size: 11px; padding: 2px 4px;")
        self.override_label.setWordWrap(True)
        self.override_label.hide()
        layout.addWidget(self.override_label)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Return), self, self._on_confirm)
        QShortcut(QKeySequence(Qt.Key_Enter), self, self._on_confirm)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._on_skip)
        QShortcut(QKeySequence(Qt.Key_Tab), self, self._on_next_pending)

    def load_group(self, group_id: int, files: list[MediaFile],
                   categories: list[CategoryNode], group: Optional[MediaGroup] = None,
                   extra_recommended_ids: set[int] = None):
        self._current_group_id = group_id
        self._current_group = group
        self._files = files
        self._categories = categories
        info_parts = [f"<b>组 #{group_id}</b>"]
        if group:
            info_parts.append(f"时间: {group.time_span_str}")
            info_parts.append(f"文件: {group.file_count} 个")
            if group.detected_tag:
                info_parts.append(f"标注: <code>{group.detected_tag}</code>")
            if group.category_path:
                info_parts.append(f"当前分类: <b>{group.category_path}</b>")
            if group.status == "conflict" and group.conflict_candidates:
                paths = [c.path for c in group.conflict_candidates]
                info_parts.append(f"⚠️ 冲突候选: {' / '.join(paths)}")
            if group.classify_method:
                info_parts.append(f"方法: {group.classify_method} (置信度 {group.confidence:.0%})")
        self.info_label.setText("  |  ".join(info_parts))
        self._clear_thumbnails()
        for idx, f in enumerate(files):
            thumb = ThumbnailWidget(f, idx)
            thumb.clicked.connect(self._on_thumb_clicked)
            name_label = QLabel(f.filename[:25])
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet("font-size: 10px; color: #666;")
            container = QWidget()
            vl = QVBoxLayout(container)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(2)
            vl.addWidget(thumb)
            vl.addWidget(name_label)
            if f.file_tag:
                tag_label = QLabel(f"🏷 {f.file_tag}")
                tag_label.setAlignment(Qt.AlignCenter)
                tag_label.setStyleSheet("font-size: 10px; color: #1976D2; font-weight: bold;")
                vl.addWidget(tag_label)
            if f.has_override:
                ov_label = QLabel(f"⚡ {f.file_category_path}")
                ov_label.setAlignment(Qt.AlignCenter)
                ov_label.setStyleSheet("font-size: 9px; color: #E65100; font-weight: bold;")
                vl.addWidget(ov_label)
            self.thumb_layout.insertWidget(self.thumb_layout.count() - 1, container)
        self.category_selector.set_categories(categories)
        recommended = set()
        if group and group.conflict_candidates:
            for c in group.conflict_candidates:
                recommended.add(c.id)
        if group and group.category_id:
            recommended.add(group.category_id)
        if extra_recommended_ids:
            recommended.update(extra_recommended_ids)
        self._recommended_ids = recommended
        self.category_selector.set_recommended_ids(recommended)
        # 将检测到的标注自动填入搜索框
        tag = group.detected_tag if group else None
        if not tag:
            tags = [f.file_tag for f in files if f.file_tag]
            tag = tags[0] if tags else None
        if tag and not group.category_id:
            self.category_selector.set_search_text(tag)
        else:
            self.category_selector.clear_search()
        if group and group.category_id:
            self.category_selector.select_category_id(group.category_id)
        elif group and group.conflict_candidates:
            self.category_selector.select_category_id(group.conflict_candidates[0].id)
        overrides = [f for f in files if f.has_override]
        if overrides:
            ov_info = ", ".join(f"{f.filename} → {f.file_category_path}" for f in overrides)
            self.override_label.setText(f"⚡ 此组有 {len(overrides)} 个文件存在单独分类覆盖: {ov_info}")
            self.override_label.show()
        else:
            self.override_label.hide()

    def _clear_thumbnails(self):
        while self.thumb_layout.count() > 1:
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_thumb_clicked(self, file_index: int):
        dlg = ImagePreviewDialog(self._files, file_index, parent=self.window())
        dlg.file_override_requested.connect(self._on_preview_override)
        dlg.exec()

    def _on_preview_override(self, file_index: int, file_path: str):
        if file_index < 0 or file_index >= len(self._files):
            return
        self._show_file_override_dialog(file_index)

    def _show_file_override_dialog(self, file_index: int):
        f = self._files[file_index]
        group_cat_path = ""
        if self._current_group and self._current_group.category_path:
            group_cat_path = self._current_group.category_path
        dlg = FileOverrideDialog(f, self._categories, group_cat_path,
                                 recommended_ids=self._recommended_ids, parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_cat_id = dlg.get_selected_category_id()
            f.file_category_id = new_cat_id
            if new_cat_id is not None:
                for cat in self._categories:
                    if cat.id == new_cat_id:
                        f.file_category_path = cat.path
                        break
            else:
                f.file_category_path = None
            self.file_category_changed.emit(f.id, new_cat_id)
            self.load_group(self._current_group_id, self._files,
                            self._categories, self._current_group)

    def _on_confirm(self):
        if self._current_group_id is None:
            return
        cat_id = self.category_selector.selected_category_id()
        if cat_id is None:
            return
        self.classification_confirmed.emit(self._current_group_id, cat_id)

    def _on_skip(self):
        if self._current_group_id is None:
            return
        self.group_skipped.emit(self._current_group_id)

    def _on_next_pending(self):
        self.next_pending_requested.emit()
