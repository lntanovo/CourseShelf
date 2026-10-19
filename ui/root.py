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

class RootMixin:
    def root_path(self) -> Path | None:
        raw = self.root_edit.text().strip()
        path = Path(raw) if raw else None
        return path if path is not None and path.is_dir() else None

    def choose_root(self):
        if self.file_worker and self.file_worker.isRunning():
            self.statusBar().showMessage("请等待归档结束或先取消批次")
            return
        initial = self.root_edit.text() if self.root_path() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择现有资料总目录", initial)
        if selected:
            self.root_edit.setText(selected)
            self.root_changed()

    def root_changed(self, *, save: bool = True, preferred: str | None = None):
        root = self.root_path()
        if root is None:
            self.root_status.setText("资料目录不存在或未选择。请选一个已有的本机文件夹；不会自动创建。")
            self.current_directory = None
            self.browser_path_label.setText("没有可浏览的资料目录")
            self.files_table.setRowCount(0)
            self.files_title.setText("文件 · 0 个")
            self.folder_tree.clear()
            self.tree_items.clear()
            self.refresh_targets()
            self.missing_label.setText("资料总目录失效；请重新选择。不会自动创建目录。")
            self.missing_combo.clear()
            return
        root = root.resolve()
        log.info("root_changed root=%s", root)
        if self.root_edit.text() != str(root):
            self.root_edit.setText(str(root))
        if save:
            try:
                save_root(root)
            except OSError as exc:
                self.root_status.setText("目录可用，但设置保存失败：" + str(exc))
        self.root_edit.setToolTip(str(root))
        self.root_status.setText("资料直接保存在：" + str(root))
        self.refresh_targets()
        self.refresh_browser(preferred=preferred or str(root), remember=save)

    def show_about(self):
        QMessageBox.information(self, "关于 CourseShelf", "完全本地的课表识别和课程资料整理工具。\n默认复制资料；移动和删除都需要明确选择。\n资料保存在窗口顶部显示的资料总目录。")

    def open_root(self):
        root = self.root_path()
        if root is None:
            self.root_status.setText("无法打开：资料总目录不存在，请重新选择。")
            return
        open_with_shell(root, self.statusBar().showMessage)

    def closeEvent(self, event):
        self._scan_pending = False
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.request_cancel()
            self.scan_worker.wait(1000)
        workers = [worker for worker in (self.worker, self.file_worker, self.scan_worker, self.undo_worker)
                   if worker is not None and worker.isRunning()]
        if workers:
            if not getattr(self, "_closing", False) and not confirm(self, "退出 CourseShelf", "取消后台任务并退出？已完成的文件会保留。", "取消任务并退出"):
                event.ignore()
                return
            for worker in workers:
                worker.cancel_requested = True
            self._closing = True
            for worker in workers:
                worker.finished.connect(self.close)
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

