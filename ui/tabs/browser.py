"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QMenu, QFileIconProvider
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QInputDialog, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import save_settings
from runtime import (log,
                     open_with_shell)
from dialogs import confirm
from tasks import ScanWorker


from ui.widgets import FileDropTree

class BrowserMixin:
    def _make_browser(self) -> QWidget:
        self.file_action_worker = None
        self._file_icon = QFileIconProvider().icon(QFileIconProvider.IconType.File)
        self._directory_workers = []
        self._tree_epoch = self._files_epoch = 0
        self._tree_loaded = set()
        self._tree_pending = set()
        self._refresh_scheduled = False
        self.view_settings_timer = QTimer(self)
        self.view_settings_timer.setSingleShot(True)
        self.view_settings_timer.setInterval(350)
        self.view_settings_timer.timeout.connect(self.flush_view_settings)
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
        self.folder_tree.itemExpanded.connect(self.expand_tree_item)
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
        self.files_table.setSortingEnabled(True)
        self.files_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_table.customContextMenuRequested.connect(self.file_context_menu)
        for key, callback in (("F5", self.refresh_browser), ("Ctrl+F", self.search_edit.setFocus),
                              ("Ctrl+O", self.open_selected_file), ("Delete", lambda: self.change_selected_file("trash"))):
            shortcut = QShortcut(key, self.files_table if key == "Delete" else self)
            if key == "Delete":
                shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(callback)
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.horizontalHeader().setResizeContentsPrecision(50)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.doubleClicked.connect(self.open_selected_file)
        files_layout.addWidget(self.files_table)
        panes.addWidget(files_box)
        panes.setSizes([320, 270])
        return card

    def refresh_browser(self, *_args, preferred=None, remember=True):
        from catalog import catalog_snapshot
        root = self.root_path()
        if root is None:
            self.root_changed(save=False)
            return
        with catalog_snapshot(root):
            previous = self._loading_inbox
            self._loading_inbox = True
            try:
                self._refresh_browser(preferred=preferred, remember=remember)
            finally:
                self._loading_inbox = previous
            if not previous and 0 <= self._selected_inbox < len(self.inbox_items):
                self.select_inbox_row(self._selected_inbox)

    def _refresh_browser(self, preferred=None, remember=True):
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
            self._files_epoch += 1
            self.files_table.setSortingEnabled(False)
            self.files_table.setRowCount(len(rows))
            for row, record in enumerate(rows):
                path = root / record["rel_path"]
                name = QTableWidgetItem(record["rel_path"])
                name.setData(Qt.ItemDataRole.UserRole, str(path))
                name.setIcon(self._file_icon)
                self.files_table.setItem(row, 0, name)
                size = QTableWidgetItem()
                size.setData(Qt.ItemDataRole.EditRole, record["size"])
                self.files_table.setItem(row, 1, size)
                self.files_table.setItem(row, 2, QTableWidgetItem(datetime.fromtimestamp(record["mtime_ns"] / 1e9).strftime("%Y-%m-%d %H:%M")))
            self.files_title.setText(f"搜索结果 · {len(rows)} 个（最多 500）")
            self.files_table.setSortingEnabled(True)
        except Exception as exc:
            log.exception("search_failed")
            self.index_status.setText("索引不可用，正在重建：" + str(exc))
            self.start_index_scan()

    def _load_tree(self, root):
        self._tree_epoch += 1
        self._tree_loaded = set()
        self._tree_pending = set()
        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()
        self.tree_items.clear()
        self._populate_tree(root)
        self.folder_tree.blockSignals(False)

    def _directory_job(self, directory, callback):
        from tasks import DirectoryWorker
        worker = DirectoryWorker(self.root_path(), directory)
        self._directory_workers.append(worker)
        worker.completed.connect(callback)
        worker.failed.connect(lambda error: self.browser_path_label.setText("目录读取失败：" + error))
        worker.finished.connect(lambda w=worker: self._directory_stopped(w))
        worker.start()

    def _directory_stopped(self, worker):
        if worker in self._directory_workers:
            self._directory_workers.remove(worker)
        worker.deleteLater()

    def _populate_tree(self, directory):
        from services.browser import read_directory
        if directory in self._tree_loaded or directory in self._tree_pending:
            return
        epoch = self._tree_epoch
        def apply(snapshot):
            if epoch != self._tree_epoch or getattr(self, "_closing", False):
                return
            self._tree_pending.discard(directory)
            self._tree_loaded.add(directory)
            folders = snapshot["folders"]
            def chunk(start=0):
                if epoch != self._tree_epoch or getattr(self, "_closing", False):
                    return
                parent = self.tree_items.get(directory)
                for path in folders[start:start + 64]:
                    if path in self.tree_items:
                        continue
                    item = QTreeWidgetItem([path.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(path))
                    item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                    if parent is None:
                        self.folder_tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    self.tree_items[path] = item
                if start + 64 < len(folders):
                    QTimer.singleShot(0, lambda: chunk(start + 64))
            chunk()
        try:
            snapshot = read_directory(self.root_path(), directory, limit=64)
            if snapshot is None:
                self._tree_pending.add(directory)
                self._directory_job(directory, apply)
            else:
                apply(snapshot)
        except (OSError, ValueError) as exc:
            self.browser_path_label.setText("目录树读取失败：" + str(exc))

    def expand_tree_item(self, item):
        self._populate_tree(Path(item.data(0, Qt.ItemDataRole.UserRole)))

    def _select_tree_path(self, path):
        root = self.root_path()
        if root is None or not path.is_relative_to(root):
            return
        current = root
        for part in path.relative_to(root).parts:
            self._populate_tree(current)
            current = current / part
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

    def show_files(self, directory, *, remember=True):
        from services.browser import read_directory
        root = self.root_path()
        if root is None:
            return
        self._files_epoch += 1
        epoch = self._files_epoch
        try:
            snapshot = read_directory(root, directory, limit=64)
        except (OSError, ValueError) as exc:
            self.browser_path_label.setText("目录读取失败：" + str(exc))
            self.files_table.setRowCount(0)
            return
        self.current_directory = directory
        self.browser_path_label.setText(str(directory))
        self.files_table.setRowCount(0)
        def apply(data):
            if epoch != self._files_epoch or getattr(self, "_closing", False):
                return
            files = data["files"]
            self.files_table.setSortingEnabled(False)
            self.files_table.setRowCount(len(files))
            self.files_title.setText(f"文件 · {len(files)} 个")
            def chunk(start=0):
                if epoch != self._files_epoch or getattr(self, "_closing", False):
                    return
                for row in range(start, min(start + 64, len(files))):
                    path, size, modified = files[row]
                    name = QTableWidgetItem(path.name)
                    name.setData(Qt.ItemDataRole.UserRole, str(path))
                    name.setIcon(self._file_icon)
                    self.files_table.setItem(row, 0, name)
                    size_item = QTableWidgetItem()
                    size_item.setData(Qt.ItemDataRole.EditRole, size)
                    self.files_table.setItem(row, 1, size_item)
                    self.files_table.setItem(row, 2, QTableWidgetItem(datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")))
                if start + 64 < len(files):
                    QTimer.singleShot(0, lambda: chunk(start + 64))
                else:
                    self.files_table.setSortingEnabled(True)
            chunk()
        if snapshot is None:
            self.files_title.setText("正在后台读取文件…")
            self._directory_job(directory, apply)
        else:
            apply(snapshot)
        if remember:
            self._pending_view_settings = (root, directory)
            self.view_settings_timer.start()

    def flush_view_settings(self):
        self.view_settings_timer.stop()
        pending = getattr(self, "_pending_view_settings", None)
        if pending:
            self._pending_view_settings = None
            try:
                save_settings(*pending)
            except OSError as exc:
                self.root_status.setText("位置记忆失败：" + str(exc))

    def request_refresh(self, **kwargs):
        self._refresh_kwargs = kwargs
        if not self._refresh_scheduled:
            self._refresh_scheduled = True
            QTimer.singleShot(0, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self):
        self._refresh_scheduled = False
        self.refresh_browser(**self._refresh_kwargs)

    def open_current_folder(self):
        if self.current_directory and self.current_directory.is_dir():
            open_with_shell(self.current_directory, self.statusBar().showMessage)
        else:
            self.browser_path_label.setText("没有可打开的目录，请先选择资料总目录。")

    def open_selected_file(self, index=None):
        item = self.files_table.item(index.row() if hasattr(index, "row") else self.files_table.currentRow(), 0)
        if item:
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            if path.is_file():
                open_with_shell(path, self.statusBar().showMessage)
            else:
                self.statusBar().showMessage("文件已被外部删除，请刷新")

    def selected_file_path(self):
        item = self.files_table.item(self.files_table.currentRow(), 0)
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def locate_selected_file(self):
        path = self.selected_file_path()
        if path and path.exists():
            try:
                subprocess.Popen(["explorer.exe", "/select," + str(path)])
            except OSError as exc:
                self.statusBar().showMessage("无法在资源管理器中定位：" + str(exc))

    def file_context_menu(self, position):
        from history import owned_record
        path = self.selected_file_path()
        if path is None:
            return
        menu = QMenu(self)
        menu.addAction("打开", self.open_selected_file)
        menu.addAction("在资源管理器中定位", self.locate_selected_file)
        menu.addAction("复制完整路径", lambda: QApplication.clipboard().setText(str(path)))
        owned = bool(owned_record(self.root_path(), path))
        for title, kind in (("重命名", "rename"), ("移至回收站", "trash")):
            action = menu.addAction(title, lambda checked=False, k=kind: self.change_selected_file(k))
            action.setEnabled(owned)
        menu.exec(self.files_table.viewport().mapToGlobal(position))

    def change_selected_file(self, kind):
        from tasks import FileActionWorker
        path = self.selected_file_path()
        if path is None or any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            return
        name = None
        if kind == "rename":
            name, ok = QInputDialog.getText(self, "重命名已归档文件", "新文件名", text=path.name)
            if not ok or name == path.name:
                return
        if not confirm(self, "重命名" if kind == "rename" else "移至回收站", str(path) + ("\n→ " + name if name else "\n此文件将进入回收站")):
            return
        self.file_action_worker = FileActionWorker(self.root_path(), path, kind, name)
        self.file_action_worker.completed.connect(self.statusBar().showMessage)
        self.file_action_worker.failed.connect(self.statusBar().showMessage)
        self.file_action_worker.finished.connect(self.request_refresh)
        self.file_action_worker.start()

