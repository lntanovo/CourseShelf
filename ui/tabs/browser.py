"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

import os
import json
import sys
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog,
    QCheckBox, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QInputDialog, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QRadioButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import build_plan, extract_candidates, load_settings, local_ocr, planned_copy_path, save_root, save_settings
from catalog import (add_category, count_contents, create_plan,
                     disk_categories, import_course, is_managed, missing_paths, plan_paths,
                     rename_category, restore_defaults, restore_missing, trash_category)
from classifier import suggest
from file_ops import Cancelled, PartialMoveError, transfer
from runtime import (acquire_instance, configure_logging, install_exception_hooks, log,
                     open_with_shell, report_exception)
from dialogs import confirm
from inbox import build_inbox
from tasks import BatchWorker, FileWorker, ScanWorker, TaskWorker, UndoWorker


from tasks import OcrWorker
from ui.widgets import DropFileEdit, ImageDropZone, FileDropTree

class BrowserMixin:
    def _make_browser(self) -> QWidget:
        card, layout = self._card("资料浏览 · 磁盘上的真实文件")
        card.setMinimumWidth(460)
        row = QHBoxLayout()
        self.browser_path_label = QLabel("尚未选择资料目录")
        self.browser_path_label.setObjectName("pathText")
        self.browser_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.browser_path_label.setWordWrap(True)
        row.addWidget(self.browser_path_label, 1)
        row.addWidget(self._button("刷新", self.refresh_browser))
        row.addWidget(self._button("打开此目录", self.open_current_folder))
        layout.addLayout(row)
        self.missing_label = QLabel("")
        self.missing_label.setObjectName("warning")
        self.missing_label.setWordWrap(True)
        layout.addWidget(self.missing_label)
        missing_row = QHBoxLayout()
        self.missing_combo = QComboBox()
        self.missing_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        missing_row.addWidget(self.missing_combo, 1)
        missing_row.addWidget(self._button("重建选中空目录", self.restore_missing_ui))
        layout.addLayout(missing_row)
        panes = QSplitter(Qt.Orientation.Vertical)
        panes.setChildrenCollapsible(False)
        layout.addWidget(panes, 1)

        tree_box = QWidget()
        tree_layout = QVBoxLayout(tree_box)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("文件夹 · 学期 → 课程 → 分类"))
        self.folder_tree = FileDropTree()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.currentItemChanged.connect(self.on_tree_selected)
        self.folder_tree.file_on_item.connect(self.file_dropped_on_tree)
        self.folder_tree.rejected.connect(self.statusBar().showMessage)
        tree_layout.addWidget(self.folder_tree)
        panes.addWidget(tree_box)

        files_box = QWidget()
        files_layout = QVBoxLayout(files_box)
        files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_title = QLabel("文件 · 0 个")
        files_layout.addWidget(self.files_title)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索文件名（全资料目录）")
        self.search_course = QLineEdit()
        self.search_course.setPlaceholderText("课程筛选")
        self.search_category = QLineEdit()
        self.search_category.setPlaceholderText("分类筛选")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.search_files)
        for widget in (self.search_edit, self.search_course, self.search_category):
            widget.textChanged.connect(lambda: self.search_timer.start())
            search_row.addWidget(widget)
        files_layout.addLayout(search_row)
        self.index_status = QLabel("索引尚未扫描")
        files_layout.addWidget(self.index_status)
        self.files_table = QTableWidget(0, 3)
        self.files_table.setHorizontalHeaderLabels(["文件名", "大小", "修改时间"])
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.doubleClicked.connect(self.open_selected_file)
        files_layout.addWidget(self.files_table)
        panes.addWidget(files_box)
        panes.setSizes([320, 270])
        return card

    def refresh_browser(self, *_args, preferred: str | None = None, remember: bool = True):
        root = self.root_path()
        if root is None:
            self.root_changed(save=False)
            return
        self._load_tree(root)
        candidate = Path(preferred) if preferred else self.current_directory or root
        try:
            valid = candidate.is_dir() and candidate.resolve().is_relative_to(root.resolve())
        except OSError:
            valid = False
        chosen = candidate if valid else root
        self.show_files(chosen, remember=remember)
        self._select_tree_path(chosen)
        if not valid and candidate != root:
            self.browser_path_label.setText("上次查看的目录已失效，已返回资料总目录：" + str(root))
        self.refresh_missing()
        self.refresh_targets()
        self.refresh_manage_categories()

        self.start_index_scan()
        self.refresh_history()

    def start_index_scan(self):
        root = self.root_path()
        if root is None:
            return
        if self.scan_worker and self.scan_worker.isRunning():
            self._scan_pending = True
            if self.scan_worker.root != root:
                self.scan_worker.request_cancel()
            return
        self._scan_pending = False
        self.index_status.setText("正在后台扫描文件索引…")
        self.scan_worker = ScanWorker(root)
        self.scan_worker.completed.connect(lambda count: self.index_status.setText(f"索引已更新：{count} 个文件"))
        self.scan_worker.completed.connect(lambda _: self.search_files() if self.has_search() else None)
        self.scan_worker.failed.connect(lambda error: self.index_status.setText("索引扫描失败：" + error))
        self.scan_worker.finished.connect(self.index_scan_stopped)
        self.scan_worker.start()

    def index_scan_stopped(self):
        if self._scan_pending and not getattr(self, "_closing", False):
            self.start_index_scan()

    def has_search(self):
        return any(widget.text().strip() for widget in (self.search_edit, self.search_course, self.search_category))

    def search_files(self):
        root = self.root_path()
        if root is None:
            return
        if not self.has_search():
            self.show_files(self.current_directory or root, remember=False)
            return
        from library_index import search
        try:
            rows = search(root, self.search_edit.text().strip(), self.search_course.text().strip(), self.search_category.text().strip())
            self.files_table.setRowCount(len(rows))
            for row, record in enumerate(rows):
                path = root / record["rel_path"]
                name = QTableWidgetItem(record["rel_path"])
                name.setData(Qt.ItemDataRole.UserRole, str(path))
                self.files_table.setItem(row, 0, name)
                self.files_table.setItem(row, 1, QTableWidgetItem(str(record["size"])))
                self.files_table.setItem(row, 2, QTableWidgetItem(datetime.fromtimestamp(record["mtime_ns"] / 1e9).strftime("%Y-%m-%d %H:%M")))
            self.files_title.setText(f"搜索结果 · {len(rows)} 个（最多 500）")
        except Exception as exc:
            log.exception("search_failed")
            self.index_status.setText("索引不可用，正在重建：" + str(exc))
            self.start_index_scan()

    def _load_tree(self, root: Path):
        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()
        self.tree_items.clear()

        def append_folders(parent_item: QTreeWidgetItem | None, parent_path: Path, depth: int):
            if depth > 2:
                return
            try:
                children = sorted((p for p in parent_path.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name.casefold())
            except OSError as exc:
                self.browser_path_label.setText("目录树读取失败：" + str(exc))
                return
            for child in children:
                item = QTreeWidgetItem([child.name])
                item.setData(0, Qt.ItemDataRole.UserRole, str(child))
                if parent_item is None:
                    self.folder_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self.tree_items[child] = item
                append_folders(item, child, depth + 1)

        append_folders(None, root, 0)
        self.folder_tree.blockSignals(False)

    def _select_tree_path(self, path: Path):
        item = self.tree_items.get(path)
        if item is None:
            return
        self.folder_tree.blockSignals(True)
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.folder_tree.setCurrentItem(item)
        self.folder_tree.scrollToItem(item)
        self.folder_tree.blockSignals(False)

    def on_tree_selected(self, current, _previous):
        if current is not None:
            self.show_files(Path(current.data(0, Qt.ItemDataRole.UserRole)))
            self.refresh_manage_categories()

    def show_files(self, directory: Path, *, remember: bool = True):
        root = self.root_path()
        if root is None:
            return
        try:
            if directory.is_symlink() or not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
                raise ValueError("所选目录已失效或不在资料总目录内")
            files = sorted((p for p in directory.iterdir() if p.is_file() and not p.is_symlink()), key=lambda p: p.name.casefold())
        except (OSError, ValueError) as exc:
            self.browser_path_label.setText("目录读取失败：" + str(exc))
            self.files_table.setRowCount(0)
            self.files_title.setText("文件 · 0 个")
            return
        self.current_directory = directory
        self.browser_path_label.setText(str(directory))
        self.files_table.setRowCount(len(files))
        for row, path in enumerate(files):
            try:
                stat = path.stat()
                size = f"{stat.st_size:,} B"
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                size, modified = "无法读取", "—"
            name_item = QTableWidgetItem(path.name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files_table.setItem(row, 0, name_item)
            self.files_table.setItem(row, 1, QTableWidgetItem(size))
            self.files_table.setItem(row, 2, QTableWidgetItem(modified))
        self.files_title.setText(f"文件 · {len(files)} 个")
        if remember:
            try:
                save_settings(root, directory)
            except OSError as exc:
                self.root_status.setText("文件可浏览，但位置记忆失败：" + str(exc))

    def open_current_folder(self):
        if self.current_directory and self.current_directory.is_dir():
            open_with_shell(self.current_directory, self.statusBar().showMessage)
        else:
            self.browser_path_label.setText("没有可打开的目录，请先选择资料总目录。")

    def open_selected_file(self, index):
        item = self.files_table.item(index.row(), 0)
        if item:
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            if path.is_file():
                open_with_shell(path, self.statusBar().showMessage)

