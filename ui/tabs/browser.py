"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QMenu, QFileIconProvider
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QInputDialog, QMessageBox, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QDateEdit, QStyle,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import save_settings
from runtime import (log,
                     open_with_shell)
from dialogs import confirm
from tasks import ScanWorker


from ui.widgets import FileDropTree, SoftComboBox as QComboBox

class BrowserMixin:
    def _make_browser(self) -> QWidget:
        self.file_action_worker = None
        self._file_icon = QFileIconProvider().icon(QFileIconProvider.IconType.File)
        self._directory_workers = []
        self._tree_epoch = self._files_epoch = 0
        self._tree_loaded = set()
        self._tree_pending = set()
        self._refresh_scheduled = False
        self._filter_updating = False
        self._filter_catalog = {}
        self._query_directory = None
        self._query_error = False
        self.view_settings_timer = QTimer(self)
        self.view_settings_timer.setSingleShot(True)
        self.view_settings_timer.setInterval(350)
        self.view_settings_timer.timeout.connect(self.flush_view_settings)
        card, layout = self._card("我的资料")
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
        self.missing_tools = QWidget()
        missing_row = QHBoxLayout(self.missing_tools)
        missing_row.setContentsMargins(0, 0, 0, 0)
        self.missing_combo = QComboBox()
        self.missing_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        missing_row.addWidget(self.missing_combo, 1)
        missing_row.addWidget(self._button("重建选中空目录", self.restore_missing_ui))
        layout.addWidget(self.missing_tools)
        self.missing_tools.hide()
        panes = QSplitter(Qt.Orientation.Horizontal)
        panes.setChildrenCollapsible(False)
        layout.addWidget(panes, 1)

        tree_box = QWidget()
        tree_layout = QVBoxLayout(tree_box)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("文件夹"))
        self.folder_tree = FileDropTree()
        self.folder_tree.setMinimumWidth(190)
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
        self.search_edit.setPlaceholderText("搜索全部资料中的文件名")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self._button("清除筛选", self.reset_search))
        files_layout.addLayout(search_row)
        filters = QHBoxLayout()
        self.search_term = QComboBox()
        self.search_course = QComboBox()
        self.search_category = QComboBox()
        for combo, label in ((self.search_term, "全部学期"), (self.search_course, "全部课程"), (self.search_category, "全部分类")):
            combo.addItem(label, "")
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            filters.addWidget(combo, 1)
        files_layout.addLayout(filters)
        dates = QHBoxLayout()
        dates.addWidget(QLabel("修改时间"))
        self.search_time = QComboBox()
        for label, key in (("不限", "all"), ("今天", "today"), ("近7天", "week"), ("近30天", "month30"), ("本月", "month"), ("自定义", "custom")):
            self.search_time.addItem(label, key)
        dates.addWidget(self.search_time, 1)
        self.file_sort = QComboBox()
        for label, key in (("最新修改", "newest"), ("最早修改", "oldest"), ("文件名", "name"), ("文件大小", "size")):
            self.file_sort.addItem(label, key)
        dates.addWidget(self.file_sort, 1)
        files_layout.addLayout(dates)
        self.date_range = QWidget()
        custom_dates = QHBoxLayout(self.date_range)
        custom_dates.setContentsMargins(0, 0, 0, 0)
        self.date_from = QDateEdit(QDate.currentDate().addDays(-29))
        self.date_until = QDateEdit(QDate.currentDate())
        for editor in (self.date_from, self.date_until):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("yyyy-MM-dd")
            editor.dateChanged.connect(self.filter_changed)
        custom_dates.addWidget(self.date_from)
        custom_dates.addWidget(QLabel("至"))
        custom_dates.addWidget(self.date_until)
        files_layout.addWidget(self.date_range)
        self.date_range.hide()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.search_files)
        self.search_edit.textChanged.connect(self.filter_changed)
        self.search_term.currentIndexChanged.connect(self.filter_term_changed)
        self.search_course.currentIndexChanged.connect(self.filter_course_changed)
        self.search_category.currentIndexChanged.connect(self.filter_changed)
        self.search_time.currentIndexChanged.connect(self.filter_changed)
        self.file_sort.currentIndexChanged.connect(self.sort_files)
        self.index_status = QLabel("索引尚未扫描")
        files_layout.addWidget(self.index_status)
        self.files_table = QTableWidget(0, 4)
        self.files_table.setHorizontalHeaderLabels(["文件名", "大小", "修改时间", "所在文件夹"])
        self.files_table.setSortingEnabled(True)
        self.files_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files_table.customContextMenuRequested.connect(self.file_context_menu)
        for key, callback in (("F5", self.refresh_browser), ("Ctrl+F", self.focus_search),
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
        self.files_table.setColumnWidth(3, 170)
        self.files_table.setColumnHidden(3, True)
        self.files_table.setWordWrap(False)
        self.files_table.setShowGrid(False)
        self.files_table.verticalHeader().setDefaultSectionSize(34)
        self.files_table.doubleClicked.connect(self.open_selected_file)
        files_layout.addWidget(self.files_table)
        panes.addWidget(files_box)
        panes.setSizes([260, 720])
        return card

    def focus_search(self):
        self.tabs.setCurrentIndex(3)
        self.search_edit.setFocus()

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
        self.refresh_filter_choices()
        self.start_index_scan()

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

    def refresh_filter_choices(self):
        selected_term = self.search_term.currentData()
        self._filter_catalog = self.course_snapshot()
        self._filter_updating = True
        self.search_term.blockSignals(True)
        self.search_term.clear()
        self.search_term.addItem("全部学期", "")
        for term in sorted({Path(key).parts[0] for key in self._filter_catalog}):
            self.search_term.addItem(term, term)
        self.search_term.setCurrentIndex(max(0, self.search_term.findData(selected_term)))
        self.search_term.blockSignals(False)
        self.populate_filter_courses()
        self._filter_updating = False

    def populate_filter_courses(self):
        selected = self.search_course.currentData()
        term = self.search_term.currentData()
        self.search_course.blockSignals(True)
        self.search_course.clear()
        self.search_course.addItem("全部课程", "")
        for key in sorted(self._filter_catalog):
            semester, course = Path(key).parts
            if not term or term == semester:
                self.search_course.addItem(course if term else f"{course} · {semester}", key)
        self.search_course.setCurrentIndex(max(0, self.search_course.findData(selected)))
        self.search_course.blockSignals(False)
        self.populate_filter_categories()

    def populate_filter_categories(self):
        selected = self.search_category.currentData()
        term, course = self.search_term.currentData(), self.search_course.currentData()
        values = set()
        for key, names in self._filter_catalog.items():
            if (not term or Path(key).parts[0] == term) and (not course or course == key):
                values.update(names)
        self.search_category.blockSignals(True)
        self.search_category.clear()
        self.search_category.addItem("全部分类", "")
        for name in sorted(values):
            self.search_category.addItem(name, name)
        self.search_category.setCurrentIndex(max(0, self.search_category.findData(selected)))
        self.search_category.blockSignals(False)

    def filter_term_changed(self, *_):
        if not self._filter_updating:
            self.populate_filter_courses()
            self.filter_changed()

    def filter_course_changed(self, *_):
        if not self._filter_updating:
            self.populate_filter_categories()
            self.filter_changed()

    def filter_changed(self, *_):
        if self._filter_updating:
            return
        self._query_directory = None
        self.date_range.setVisible(self.search_time.currentData() == "custom")
        self.search_timer.start()

    def reset_search_controls(self):
        self._filter_updating = True
        self.search_edit.clear()
        for combo in (self.search_term, self.search_course, self.search_category, self.search_time):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.populate_filter_courses()
        self.date_range.hide()
        self.search_timer.stop()
        self._filter_updating = False
        self._query_directory = None
        if self._query_error:
            self.index_status.clear()
            self._query_error = False

    def reset_search(self):
        self.reset_search_controls()
        self.show_files(self.root_path(), remember=False)

    def has_search(self):
        return bool(self.search_edit.text().strip() or self.search_term.currentData() or self.search_course.currentData()
                    or self.search_category.currentData() or self.search_time.currentData() != "all" or self._query_directory)

    def sort_files(self, *_):
        if self.has_search():
            self.search_files()
        else:
            self.apply_file_sort()

    def apply_file_sort(self):
        key = self.file_sort.currentData()
        column = {"newest": 2, "oldest": 2, "name": 0, "size": 1}.get(key, 0)
        order = Qt.SortOrder.DescendingOrder if key in {"newest", "size"} else Qt.SortOrder.AscendingOrder
        self.files_table.sortItems(column, order)

    def search_files(self):
        root = self.root_path()
        if root is None:
            return
        if not self.has_search():
            self.show_files(self.current_directory or root, remember=False)
            return
        from library_index import search
        from services.query_dates import time_window
        self._files_epoch += 1
        try:
            lower, upper = time_window(self.search_time.currentData(), self.date_from.date().toPython(), self.date_until.date().toPython())
            key = self.search_course.currentData()
            term = Path(key).parts[0] if key else self.search_term.currentData() or ""
            course = Path(key).name if key else ""
            rows = search(root, self.search_edit.text().strip(), course, self.search_category.currentData() or "",
                          semester=term, modified_from=lower, modified_before=upper, scope=self._query_directory,
                          exact=True, sort=self.file_sort.currentData())
            self.files_table.setSortingEnabled(False)
            self.files_table.setColumnHidden(3, False)
            self.files_table.setRowCount(len(rows))
            for row, record in enumerate(rows):
                path = root / record["rel_path"]
                name = QTableWidgetItem(path.name)
                name.setData(Qt.ItemDataRole.UserRole, str(path))
                name.setToolTip(str(path))
                name.setIcon(self._file_icon)
                self.files_table.setItem(row, 0, name)
                size = QTableWidgetItem()
                size.setData(Qt.ItemDataRole.EditRole, record["size"])
                self.files_table.setItem(row, 1, size)
                self.files_table.setItem(row, 2, QTableWidgetItem(datetime.fromtimestamp(record["mtime_ns"] / 1e9).strftime("%Y-%m-%d %H:%M")))
                location = QTableWidgetItem(str(Path(record["rel_path"]).parent))
                location.setToolTip(str(path.parent))
                self.files_table.setItem(row, 3, location)
            self.files_title.setText(f"{len(rows)} 个文件" + (" · 仅显示前500项" if len(rows) == 500 else ""))
            self.browser_path_label.setText(str(self._query_directory) if self._query_directory else "全部资料")
            self.files_table.setSortingEnabled(True)
            self.apply_file_sort()
            if self._query_error:
                self.index_status.clear()
                self._query_error = False
        except ValueError as exc:
            self._query_error = True
            self.index_status.setText(str(exc))
            self.files_table.setRowCount(0)
            self.files_title.setText("0 个文件")
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
        top = QTreeWidgetItem([root.name])
        top.setData(0, Qt.ItemDataRole.UserRole, str(root))
        top.setToolTip(0, str(root))
        top.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.folder_tree.addTopLevelItem(top)
        self.tree_items[root] = top
        top.setExpanded(True)
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
                    item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
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
            self.reset_search_controls()
            self.show_files(Path(current.data(0, Qt.ItemDataRole.UserRole)))

    def show_files(self, directory, *, remember=True):
        from services.browser import read_directory
        root = self.root_path()
        if root is None:
            return
        self._query_directory = None
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
            if data["folders"] or self.has_search():
                if not self.has_search():
                    self._query_directory = directory
                self.search_files()
                return
            files = [entry for entry in data["files"] if not entry[0].name.startswith(".courseshelf")]
            self.files_table.setColumnHidden(3, True)
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
                    self.apply_file_sort()
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
        directory = (self._query_directory or self.root_path()) if self.has_search() else self.current_directory
        if directory and directory.is_dir():
            open_with_shell(directory, self.statusBar().showMessage)
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
        if path is None or any(worker and worker.isRunning() for worker in (self.file_worker, self.file_action_worker)):
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


    def refresh_missing(self):
        from catalog import missing_paths
        root = self.root_path()
        self.missing_combo.clear()
        self.missing_tools.hide()
        if root is None:
            return
        try:
            from catalog import current_catalog
            data = current_catalog(root)
            if data.get("_read_only"):
                self.missing_label.setText(data["_warning"])
                return
            missing = missing_paths(root)
        except (OSError, ValueError) as exc:
            self.missing_label.setText("管理记录不可读取；仍可浏览磁盘文件：" + str(exc))
            return
        for path in missing:
            self.missing_combo.addItem(str(path), str(path))
        self.missing_tools.setVisible(bool(missing))
        self.missing_label.setText(f"已在磁盘上缺失 {len(missing)} 个受管目录；不会自动复原。" if missing else "")

    def restore_missing_ui(self):
        from catalog import restore_missing
        raw = self.missing_combo.currentData()
        if not raw:
            return
        root = self.root_path()
        path = Path(raw)
        try:
            ancestors = [p for p in reversed(path.parents) if p != root and p.is_relative_to(root) and not p.is_dir()]
            preview = "\n".join(str(p) for p in [*ancestors, path])
            if QMessageBox.question(self, "重建空目录", "只重建文件夹，不恢复其中丢失的文件：\n" + preview, defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                restore_missing(root, path)
                self.refresh_browser()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "重建失败", str(exc))

