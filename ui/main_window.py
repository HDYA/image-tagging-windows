"""
媒体文件智能分类系统 - 主窗口
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QAction, QKeySequence, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMenuBar, QMenu, QToolBar, QStatusBar, QLabel, QPushButton,
    QFileDialog, QMessageBox, QProgressDialog, QApplication,
    QTabWidget, QTextEdit, QComboBox, QSpinBox, QCheckBox,
    QGroupBox, QFormLayout, QLineEdit, QDialogButtonBox,
    QDialog, QListWidget, QAbstractItemView
)

from core.config import AppConfig
from core.database import Database
from core.scanner import scan_source_files, group_by_time
from core.category_tree import scan_archive_tree, parse_manual_categories, PinyinIndex
from core.classifier import Classifier
from core.exporter import Exporter
from core.models import MediaGroup

from .category_panel import CategoryPanel
from .group_panel import GroupPanel
from .review_panel import ReviewPanel

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

    def run(self):
        try:
            files = scan_source_files(self.config,
                progress_callback=lambda d, t: self.progress.emit(d, t))
            self.finished.emit(files)
        except Exception as e:
            self.error.emit(str(e))


class ClassifyWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, classifier: Classifier, groups: list):
        super().__init__()
        self.classifier = classifier
        self.groups = groups

    def run(self):
        try:
            stats = self.classifier.classify_all(self.groups,
                progress_callback=lambda d, t: self.progress.emit(d, t))
            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = AppConfig()
        self.db: Optional[Database] = None
        self.pinyin_index = PinyinIndex()
        self.groups: list[MediaGroup] = []
        self.face_engine = None
        self._setup_ui()
        self._setup_menus()
        self._setup_shortcuts()
        self._setup_statusbar()
        self._save_indicator_timer = QTimer(self)
        self._save_indicator_timer.timeout.connect(self._update_save_indicator)
        self._save_indicator_timer.start(5000)
        self.setWindowTitle("Image Tagging Desktop")
        self.resize(1400, 900)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        self.category_panel = CategoryPanel()
        splitter.addWidget(self.category_panel)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.btn_scan = QPushButton("📂 扫描源文件")
        self.btn_scan.clicked.connect(self._on_scan)
        toolbar.addWidget(self.btn_scan)
        self.btn_classify = QPushButton("🔍 自动分类")
        self.btn_classify.clicked.connect(self._on_classify)
        self.btn_classify.setEnabled(False)
        toolbar.addWidget(self.btn_classify)
        self.btn_export = QPushButton("📤 导出结果")
        self.btn_export.clicked.connect(self._on_export)
        toolbar.addWidget(self.btn_export)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("显示:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "待处理", "已自动分类", "冲突", "待确认", "已确认", "已跳过"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_combo)
        right_layout.addLayout(toolbar)
        review_splitter = QSplitter(Qt.Vertical)
        self.group_panel = GroupPanel()
        self.group_panel.group_selected.connect(self._on_group_selected)
        review_splitter.addWidget(self.group_panel)
        self.review_panel = ReviewPanel()
        self.review_panel.classification_confirmed.connect(self._on_classification_confirmed)
        self.review_panel.group_skipped.connect(self._on_group_skipped)
        self.review_panel.file_category_changed.connect(self._on_file_category_changed)
        review_splitter.addWidget(self.review_panel)
        review_splitter.setSizes([400, 300])
        right_layout.addWidget(review_splitter)
        splitter.addWidget(right_widget)
        splitter.setSizes([280, 1100])

    def _setup_menus(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")
        act_open = file_menu.addAction("打开项目数据库...")
        act_open.triggered.connect(self._on_open_project)
        act_new = file_menu.addAction("新建项目...")
        act_new.triggered.connect(self._on_new_project)
        file_menu.addSeparator()
        act_import = file_menu.addAction("导入类别列表 (手动)...")
        act_import.triggered.connect(self._on_import_categories)
        act_scan_archive = file_menu.addAction("扫描存档目录...")
        act_scan_archive.triggered.connect(self._on_scan_archive)
        file_menu.addSeparator()
        act_save = file_menu.addAction("💾 立即保存 (Ctrl+S)")
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._on_manual_save)
        act_settings = file_menu.addAction("设置...")
        act_settings.triggered.connect(self._on_settings)
        file_menu.addSeparator()
        act_quit = file_menu.addAction("退出(&Q)")
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        export_menu = menubar.addMenu("导出(&E)")
        export_menu.addAction("导出 JSON...").triggered.connect(lambda: self._do_export("json"))
        export_menu.addAction("导出 CSV...").triggered.connect(lambda: self._do_export("csv"))
        export_menu.addAction("导出 PowerShell (复制)...").triggered.connect(lambda: self._do_export("ps_copy"))
        export_menu.addAction("导出 PowerShell (移动)...").triggered.connect(lambda: self._do_export("ps_move"))
        export_menu.addAction("导出 Batch (复制)...").triggered.connect(lambda: self._do_export("bat_copy"))
        face_menu = menubar.addMenu("人脸识别(&R)")
        self.act_face_toggle = face_menu.addAction("启用人脸模块")
        self.act_face_toggle.setCheckable(True)
        self.act_face_toggle.setChecked(False)
        self.act_face_toggle.triggered.connect(self._on_toggle_face)
        face_menu.addAction("构建人脸库...").triggered.connect(self._on_build_face_db)

    def _setup_shortcuts(self):
        pass

    def _setup_statusbar(self):
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label, 1)
        self.save_indicator = QLabel("")
        self.save_indicator.setStyleSheet("padding: 0 8px;")
        self.statusBar().addPermanentWidget(self.save_indicator)
        self.stats_label = QLabel("")
        self.statusBar().addPermanentWidget(self.stats_label)

    def _update_stats(self):
        if not self.db:
            return
        counts = self.db.get_group_count_by_status()
        total = self.db.get_total_group_count()
        parts = [f"总计 {total} 组"]
        status_names = {'auto': '自动分类', 'confirmed': '已确认', 'conflict': '冲突',
                        'confirm': '待确认', 'pending': '待处理', 'skipped': '已跳过'}
        for key, name in status_names.items():
            if key in counts:
                parts.append(f"{name} {counts[key]}")
        self.stats_label.setText(" | ".join(parts))

    def _update_save_indicator(self):
        if not self.db:
            self.save_indicator.setText("")
            return
        if self.db.is_dirty:
            self.save_indicator.setText("🔴 未保存")
            self.save_indicator.setStyleSheet("color: #D32F2F; font-weight: bold; padding: 0 8px;")
        else:
            self.save_indicator.setText("🟢 已保存")
            self.save_indicator.setStyleSheet("color: #388E3C; padding: 0 8px;")

    def _on_manual_save(self):
        if not self.db:
            return
        self.db.save_to_disk()
        self._update_save_indicator()
        self.status_label.setText("已保存到磁盘")

    def closeEvent(self, event):
        if self.db and self.db.is_dirty:
            reply = QMessageBox.question(self, "保存确认", "有未保存的数据，是否保存后退出？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if reply == QMessageBox.Save:
                self.db.save_to_disk()
                self.db.close()
                event.accept()
            elif reply == QMessageBox.Discard:
                self.db.close()
                event.accept()
            else:
                event.ignore()
                return
        else:
            if self.db:
                self.db.close()
            event.accept()

    def _on_new_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "新建项目数据库", "", "SQLite Database (*.db)")
        if not path:
            return
        self._open_db(path)
        self.status_label.setText(f"新建项目: {path}")

    def _on_open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开项目数据库", "", "SQLite Database (*.db)")
        if not path:
            return
        self._open_db(path)
        self._reload_data()
        self.status_label.setText(f"已打开: {path}")

    def _open_db(self, path: str):
        if self.db:
            self.db.close()
        self.db = Database(path, auto_save_interval=self.config.auto_save_interval)
        self.db.open()
        self.config.db_path = path
        self._update_save_indicator()

    def _reload_data(self):
        if not self.db:
            return
        cats = self.db.get_all_categories()
        self.category_panel.load_categories(cats)
        self.pinyin_index.build(cats)
        self._refresh_group_list()
        self._update_stats()

    def _on_scan_archive(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择存档根目录")
        if not dir_path:
            return
        self.config.archive_root = dir_path
        cats = scan_archive_tree(dir_path)
        if not self.db:
            QMessageBox.warning(self, "提示", "请先新建或打开项目数据库")
            return
        for cat in cats:
            cat.id = self.db.upsert_category(cat)
        self.pinyin_index.build(cats)
        self.category_panel.load_categories(cats)
        conflicts = self.pinyin_index.conflicts
        if conflicts:
            msg = f"发现 {len(conflicts)} 个拼音冲突:\n\n"
            for key, cc in list(conflicts.items())[:10]:
                msg += f"  '{key}' -> {', '.join(c.path for c in cc)}\n"
            QMessageBox.information(self, "拼音冲突", msg)
        self.status_label.setText(f"已加载 {len(cats)} 个类别")

    def _on_import_categories(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择类别列表文件", "",
            "文本文件 (*.txt *.tsv *.csv);;所有文件 (*)")
        if not path or not self.db:
            return
        text = Path(path).read_text(encoding='utf-8')
        cats = parse_manual_categories(text)
        for cat in cats:
            cat.id = self.db.upsert_category(cat)
        self.pinyin_index.build(cats)
        self.category_panel.load_categories(cats)
        self.status_label.setText(f"已导入 {len(cats)} 个类别")

    def _on_scan(self):
        if not self.db:
            QMessageBox.warning(self, "提示", "请先新建或打开项目数据库")
            return
        dirs = QFileDialog.getExistingDirectory(self, "选择待分类文件目录")
        if not dirs:
            return
        self.config.source_dirs = [dirs]
        self.progress = QProgressDialog("正在扫描文件...", "取消", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(0)
        self.progress.show()
        self.scan_worker = ScanWorker(self.config)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.error.connect(self._on_scan_error)
        self.scan_worker.start()

    def _on_scan_progress(self, done: int, total: int):
        if hasattr(self, 'progress') and self.progress:
            self.progress.setMaximum(total)
            self.progress.setValue(done)
            self.progress.setLabelText(f"正在扫描: {done}/{total} 个文件")

    def _on_scan_finished(self, files):
        if hasattr(self, 'progress') and self.progress:
            self.progress.close()
        self.groups = group_by_time(files, gap_seconds=self.config.group_gap_seconds,
                                     large_threshold=self.config.large_group_threshold)
        for group in self.groups:
            group.id = self.db.insert_group(group)
            for f in group.files:
                f.group_id = group.id
            self.db.insert_files_batch(group.files)
        self._refresh_group_list()
        self._update_stats()
        self.btn_classify.setEnabled(True)
        self.status_label.setText(f"扫描完成: {len(files)} 个文件, {len(self.groups)} 个分组")

    def _on_scan_error(self, error_msg: str):
        if hasattr(self, 'progress') and self.progress:
            self.progress.close()
        QMessageBox.critical(self, "扫描失败", error_msg)

    def _on_classify(self):
        if not self.groups:
            QMessageBox.warning(self, "提示", "请先扫描文件")
            return
        classifier = Classifier(self.config, self.db, self.pinyin_index, self.face_engine)
        self.progress = QProgressDialog("正在自动分类...", "取消", 0, len(self.groups), self)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.show()
        self.classify_worker = ClassifyWorker(classifier, self.groups)
        self.classify_worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self.classify_worker.finished.connect(self._on_classify_finished)
        self.classify_worker.error.connect(lambda e: QMessageBox.critical(self, "分类失败", e))
        self.classify_worker.start()

    def _on_classify_finished(self, stats: dict):
        if hasattr(self, 'progress') and self.progress:
            self.progress.close()
        self._refresh_group_list()
        self._update_stats()
        msg = "分类完成:\n"
        for key, count in stats.items():
            msg += f"  {key}: {count}\n"
        QMessageBox.information(self, "分类结果", msg)

    def _on_group_selected(self, group_id: int):
        if not self.db:
            return
        files = self.db.get_files_for_group(group_id)
        cats = self.db.get_all_categories()
        group_data = None
        for g in self.groups:
            if g.id == group_id:
                group_data = g
                break
        self.review_panel.load_group(group_id, files, cats, group_data)

    def _on_classification_confirmed(self, group_id: int, category_id: int):
        if not self.db:
            return
        cat = self.db.get_category_by_id(category_id)
        self.db.update_group_classification(group_id, category_id, 1.0, "manual", "confirmed")
        for g in self.groups:
            if g.id == group_id:
                g.category_id = category_id
                g.category_path = cat.path if cat else ""
                g.status = "confirmed"
                g.confidence = 1.0
                break
        self._refresh_group_list()
        self._update_stats()
        self.group_panel.select_next_pending()

    def _on_group_skipped(self, group_id: int):
        if not self.db:
            return
        self.db.update_group_classification(group_id, None, 0.0, "", "skipped")
        for g in self.groups:
            if g.id == group_id:
                g.status = "skipped"
                break
        self._refresh_group_list()
        self._update_stats()
        self.group_panel.select_next_pending()

    def _on_file_category_changed(self, file_id: int, category_id):
        if not self.db:
            return
        cat_id = category_id if isinstance(category_id, int) else None
        self.db.update_file_category(file_id, cat_id)

    def _on_filter_changed(self, text: str):
        filter_map = {"全部": None, "待处理": "pending", "已自动分类": "auto",
                      "冲突": "conflict", "待确认": "confirm", "已确认": "confirmed", "已跳过": "skipped"}
        self.group_panel.set_filter(filter_map.get(text))

    def _refresh_group_list(self):
        self.group_panel.load_groups(self.groups)

    def _on_export(self):
        self._do_export("json")

    def _do_export(self, format_type: str):
        if not self.db:
            QMessageBox.warning(self, "提示", "请先打开项目")
            return
        filters = {"json": "JSON (*.json)", "csv": "CSV (*.csv)",
                   "ps_copy": "PowerShell (*.ps1)", "ps_move": "PowerShell (*.ps1)",
                   "bat_copy": "Batch (*.bat)"}
        path, _ = QFileDialog.getSaveFileName(self, "导出分类结果", "",
            filters.get(format_type, "所有文件 (*)"))
        if not path:
            return
        exporter = Exporter(self.db, self.config.archive_root)
        try:
            if format_type == "json":
                count = exporter.export_json(path)
            elif format_type == "csv":
                count = exporter.export_csv(path)
            elif format_type == "ps_copy":
                count = exporter.export_powershell(path, move=False)
            elif format_type == "ps_move":
                count = exporter.export_powershell(path, move=True)
            elif format_type == "bat_copy":
                count = exporter.export_batch(path, move=False)
            else:
                return
            QMessageBox.information(self, "导出完成", f"已导出 {count} 个文件 -> {path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _on_toggle_face(self, checked: bool):
        if checked:
            try:
                from core.face_engine import FaceEngine, is_face_available
                if not is_face_available():
                    QMessageBox.warning(self, "人脸模块不可用", "缺少依赖")
                    self.act_face_toggle.setChecked(False)
                    return
                self.face_engine = FaceEngine(backend=self.config.face_backend)
                self.face_engine.initialize()
                self.config.face_enabled = True
                self.status_label.setText("人脸模块已启用")
            except Exception as e:
                QMessageBox.critical(self, "初始化失败", str(e))
                self.act_face_toggle.setChecked(False)
        else:
            self.face_engine = None
            self.config.face_enabled = False
            self.status_label.setText("人脸模块已禁用")

    def _on_build_face_db(self):
        if not self.face_engine:
            QMessageBox.warning(self, "提示", "请先启用人脸模块")
            return
        QMessageBox.information(self, "提示", "将从存档照片中提取人脸特征。")

    def _on_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = dlg.get_config()


class SettingsDialog(QDialog):
    TIMESTAMP_SOURCE_LABELS = {
        "exif": "EXIF 拍摄时间", "mtime": "文件修改时间",
        "ctime": "文件创建时间", "filename": "文件名解析"}

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = AppConfig()
        for attr in vars(config):
            if not attr.startswith('_'):
                setattr(self.config, attr, getattr(config, attr))
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        ts_box = QGroupBox("时间戳排序优先级")
        ts_layout = QVBoxLayout(ts_box)
        ts_desc = QLabel("按从上到下的顺序依次尝试获取时间戳，取第一个成功的。")
        ts_desc.setStyleSheet("color: #666; font-size: 11px;")
        ts_desc.setWordWrap(True)
        ts_layout.addWidget(ts_desc)
        ts_inner = QHBoxLayout()
        self.ts_list = QListWidget()
        self.ts_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.ts_list.setDefaultDropAction(Qt.MoveAction)
        self.ts_list.setMaximumHeight(140)
        for src in self.config.timestamp_priority:
            label = self.TIMESTAMP_SOURCE_LABELS.get(src, src)
            self.ts_list.addItem(f"{label}  ({src})")
        ts_inner.addWidget(self.ts_list, 1)
        btn_col = QVBoxLayout()
        btn_up = QPushButton("⬆ 上移")
        btn_up.setFixedWidth(80)
        btn_up.clicked.connect(self._ts_move_up)
        btn_col.addWidget(btn_up)
        btn_down = QPushButton("⬇ 下移")
        btn_down.setFixedWidth(80)
        btn_down.clicked.connect(self._ts_move_down)
        btn_col.addWidget(btn_down)
        btn_col.addStretch()
        ts_inner.addLayout(btn_col)
        ts_layout.addLayout(ts_inner)
        layout.addWidget(ts_box)
        group_box = QGroupBox("分组设置")
        form = QFormLayout(group_box)
        self.gap_spin = QSpinBox()
        self.gap_spin.setRange(1, 300)
        self.gap_spin.setValue(int(self.config.group_gap_seconds))
        self.gap_spin.setSuffix(" 秒")
        form.addRow("相邻文件时间阈值:", self.gap_spin)
        self.large_spin = QSpinBox()
        self.large_spin.setRange(5, 200)
        self.large_spin.setValue(self.config.large_group_threshold)
        form.addRow("超大组告警阈值:", self.large_spin)
        self.auto_save_spin = QSpinBox()
        self.auto_save_spin.setRange(0, 600)
        self.auto_save_spin.setValue(int(self.config.auto_save_interval))
        self.auto_save_spin.setSuffix(" 秒")
        form.addRow("自动保存间隔:", self.auto_save_spin)
        layout.addWidget(group_box)
        face_box = QGroupBox("人脸识别设置")
        face_form = QFormLayout(face_box)
        self.face_backend_combo = QComboBox()
        self.face_backend_combo.addItems(["directml", "rocm", "cpu"])
        self.face_backend_combo.setCurrentText(self.config.face_backend)
        face_form.addRow("推理后端:", self.face_backend_combo)
        layout.addWidget(face_box)
        path_box = QGroupBox("路径设置")
        path_form = QFormLayout(path_box)
        self.archive_edit = QLineEdit(self.config.archive_root)
        path_form.addRow("存档根目录:", self.archive_edit)
        layout.addWidget(path_box)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _ts_get_source_key(self, display_text: str) -> str:
        import re
        m = re.search(r'\((\w+)\)\s*$', display_text)
        return m.group(1) if m else display_text.strip()

    def _ts_move_up(self):
        row = self.ts_list.currentRow()
        if row > 0:
            item = self.ts_list.takeItem(row)
            self.ts_list.insertItem(row - 1, item)
            self.ts_list.setCurrentRow(row - 1)

    def _ts_move_down(self):
        row = self.ts_list.currentRow()
        if row < self.ts_list.count() - 1:
            item = self.ts_list.takeItem(row)
            self.ts_list.insertItem(row + 1, item)
            self.ts_list.setCurrentRow(row + 1)

    def get_config(self) -> AppConfig:
        priority = []
        for i in range(self.ts_list.count()):
            key = self._ts_get_source_key(self.ts_list.item(i).text())
            priority.append(key)
        self.config.timestamp_priority = priority
        self.config.group_gap_seconds = self.gap_spin.value()
        self.config.large_group_threshold = self.large_spin.value()
        self.config.auto_save_interval = self.auto_save_spin.value()
        self.config.face_backend = self.face_backend_combo.currentText()
        self.config.archive_root = self.archive_edit.text()
        return self.config
