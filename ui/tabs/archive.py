"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QMenu,
    QSizePolicy, QTableWidgetItem,
    QRadioButton, QVBoxLayout, QWidget,
)

from catalog import (disk_categories)
from runtime import (open_with_shell)
from inbox import build_inbox
from tasks import BatchWorker


from ui.widgets import DropFileEdit, StatusLabel, InboxTable, SoftComboBox as QComboBox

class ArchiveMixin:
    def _make_archive_tab(self) -> QWidget:
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        scroll, layout = self._scroll_content()
        outer.addWidget(scroll, 1)
        card, card_layout = self._card("收件箱")
        card_layout.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(self._button("添加文件", self.choose_file))
        row.addWidget(self._button("添加文件夹", self.choose_folder))
        row.addStretch()
        row.addWidget(self._button("应用高置信建议", self.apply_suggestions))
        more = self._button("更多 ···", lambda: None)
        menu = QMenu(more)
        menu.addAction("仅重试失败项", self.retry_failed)
        menu.addAction("清空收件箱", self.clear_inbox)
        more.setMenu(menu)
        row.addWidget(more)
        card_layout.addLayout(row)
        self.source_edit = DropFileEdit()
        self.source_edit.setPlaceholderText("拖入文件或文件夹，也可在这里粘贴路径")
        self.source_edit.file_dropped.connect(self.add_to_inbox)
        self.source_edit.returnPressed.connect(lambda: self.source_text_changed(self.source_edit.text()))
        card_layout.addWidget(self.source_edit)
        self.inbox_table = InboxTable()
        self.inbox_table.file_dropped.connect(self.add_to_inbox)
        self.inbox_table.setHorizontalHeaderLabels(["文件", "大小", "课程", "分类", "方式", "状态"])
        self.inbox_table.setMinimumHeight(165)
        self.inbox_table.setWordWrap(False)
        self.inbox_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inbox_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.inbox_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inbox_table.setShowGrid(False)
        self.inbox_table.verticalHeader().hide()
        self.inbox_table.verticalHeader().setDefaultSectionSize(42)
        self.inbox_table.currentCellChanged.connect(self.select_inbox_row)
        self.inbox_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.inbox_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((180, 65, 210, 105, 80, 170)):
            if column:
                self.inbox_table.setColumnWidth(column, width)
        card_layout.addWidget(self.inbox_table, 1)
        inbox_layout = card_layout
        layout.addWidget(card, 1)

        targets = QWidget()
        row = QHBoxLayout(targets)
        row.setContentsMargins(0, 0, 0, 0)
        for label, name, callback in (("学期", "archive_semester_combo", self.refresh_courses),
                                       ("课程", "course_combo", self.refresh_categories),
                                       ("分类", "category_combo", self.update_destination)):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            combo = QComboBox()
            combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            combo.currentIndexChanged.connect(callback)
            setattr(self, name, combo)
            column.addWidget(combo)
            row.addLayout(column, 1)
        self.apply_scope = QComboBox()
        self.apply_scope.addItem("选中项", "selected")
        self.apply_scope.addItem("全部待整理", "all")
        row.addWidget(self.apply_scope)
        row.addWidget(self._button("设置目标", self.apply_batch_target))
        inbox_layout.insertWidget(2, targets)
        self.archive_choice_status = StatusLabel()
        self.archive_choice_status.setWordWrap(True)
        self.archive_choice_status.setObjectName("muted")
        inbox_layout.addWidget(self.archive_choice_status)

        footer = QFrame()
        footer.setObjectName("actionBar")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 12)
        row = QHBoxLayout()
        self.execute_scope = QComboBox()
        self.execute_scope.addItem("全部待整理", "all")
        self.execute_scope.addItem("仅选中项", "selected")
        self.execute_scope.currentIndexChanged.connect(self.update_archive_actions)
        row.addWidget(self.execute_scope)
        self.copy_radio = QRadioButton("复制")
        self.copy_radio.setChecked(True)
        self.move_radio = QRadioButton("移动")
        self.move_radio.setToolTip("显式选择后，每项验证大小与 SHA-256，再删除来源")
        row.addWidget(self.copy_radio)
        row.addWidget(self.move_radio)
        self.copy_radio.toggled.connect(self.batch_mode_changed)
        self.move_radio.toggled.connect(self.batch_mode_changed)
        row.addStretch()
        self.retry_button = self._button("重试失败项", self.retry_failed)
        self.retry_button.hide()
        row.addWidget(self.retry_button)
        self.cancel_file_button = self._button("取消", self.cancel_file)
        self.cancel_file_button.setEnabled(False)
        row.addWidget(self.cancel_file_button)
        self.copy_button = self._button("执行 0 项", self.archive_file, True)
        row.addWidget(self.copy_button)
        footer_layout.addLayout(row)
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        footer_layout.addWidget(self.file_progress)
        result_row = QHBoxLayout()
        self.archive_status = QLabel("")
        self.source_edit.rejected.connect(self.archive_status.setText)
        self.archive_status.setWordWrap(True)
        self.archive_status.setObjectName("muted")
        result_row.addWidget(self.archive_status, 1)
        open_target = self._button("打开目标文件夹", self.open_destination)
        open_target.setObjectName("quiet")
        result_row.addWidget(open_target)
        footer_layout.addLayout(result_row)
        outer.addWidget(footer)
        self.inbox_table.itemSelectionChanged.connect(self.update_archive_actions)
        self.update_archive_actions()
        return body

    def refresh_targets(self, *_args, preferred: str | None = None):
        root = self.root_path()
        selected = preferred or self.archive_semester_combo.currentText()
        try:
            semesters = sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name.casefold()) if root else []
        except OSError as exc:
            semesters = []
            self.archive_choice_status.setText("学期目录读取失败：" + str(exc))
        self.archive_semester_combo.blockSignals(True)
        self.archive_semester_combo.clear()
        if semesters:
            for path in semesters:
                self.archive_semester_combo.addItem(path.name, str(path))
        else:
            self.archive_semester_combo.addItem("暂无学期 · 请先生成目录", None)
        self.archive_semester_combo.setEnabled(bool(semesters))
        index = self.archive_semester_combo.findText(selected)
        if index >= 0:
            self.archive_semester_combo.setCurrentIndex(index)
        self.archive_semester_combo.blockSignals(False)
        self.refresh_courses()

    def refresh_courses(self, *_):
        selected = self.course_combo.currentText()
        semester_data = self.archive_semester_combo.currentData()
        semester_path = Path(semester_data) if semester_data else None
        try:
            courses = sorted((p for p in semester_path.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name.casefold()) if semester_path and semester_path.is_dir() else []
        except OSError as exc:
            courses = []
            self.archive_choice_status.setText("课程目录读取失败：" + str(exc))
        self.course_combo.blockSignals(True)
        self.course_combo.clear()
        self.course_combo.addItem("选择课程", None)
        if courses:
            for path in courses:
                self.course_combo.addItem(path.name, str(path))
        else:
            self.course_combo.addItem("暂无课程 · 请先生成目录", None)
        self.course_combo.setEnabled(bool(courses))
        index = self.course_combo.findText(selected)
        if index >= 0:
            self.course_combo.setCurrentIndex(index)
        self.course_combo.blockSignals(False)
        if not semester_data:
            self.archive_choice_status.setText("资料目录下暂无学期文件夹。请先在“生成目录”页创建。")
        elif not courses:
            self.archive_choice_status.setText("该学期下暂无课程文件夹。请先生成目录或更换学期。")
        else:
            self.archive_choice_status.clear()
        self.refresh_categories()

    def refresh_categories(self, *_):
        selected = self.category_combo.currentText()
        course_data = self.course_combo.currentData()
        try:
            categories = sorted((p.name for p in Path(course_data).iterdir() if p.is_dir() and not p.is_symlink()), key=str.casefold) if course_data else []
        except OSError:
            categories = []
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("选择分类", None)
        self.category_combo.addItems(categories)
        self.category_combo.setEnabled(bool(categories))
        index = self.category_combo.findText(selected)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)
        self.update_destination()

    def target_directory(self) -> Path | None:
        root = self.root_path()
        course_data = self.course_combo.currentData()
        category = self.category_combo.currentText()
        if root and course_data and category and self.category_combo.currentIndex() > 0:
            course_path = Path(course_data)
            target = course_path / category
            if (not course_path.is_symlink() and course_path.is_dir() and not target.is_symlink()
                    and target.is_dir() and target.resolve().is_relative_to(root.resolve())):
                return target
        return None

    def update_destination(self, *_):
        if not self._loading_inbox and len(self.selected_inbox_rows()) <= 1:
            self.sync_selected_inbox()
        self.update_archive_actions()

    def course_snapshot(self):
        root = self.root_path()
        result = {}
        if root:
            for semester in root.iterdir():
                if not semester.is_dir() or semester.is_symlink() or semester.is_junction():
                    continue
                for course in semester.iterdir():
                    if course.is_dir() and not course.is_symlink() and not course.is_junction():
                        result[semester.name + "/" + course.name] = disk_categories(root, semester.name, course.name)
        return result

    def choose_file(self):
        selected, _ = QFileDialog.getOpenFileNames(self, "选择待归档文件")
        if selected:
            self.add_to_inbox(selected)

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "选择待归档文件夹")
        if selected:
            self.add_to_inbox([selected])

    def source_text_changed(self, raw):
        if self._loading_inbox or not raw.strip():
            return
        path = Path(raw.strip())
        if not path.exists():
            self.archive_status.setText("路径不存在")
            return
        self.add_to_inbox([path])

    def add_to_inbox(self, paths, *, replace=False, apply=False, target=None):
        if self.file_worker and self.file_worker.isRunning():
            return
        try:
            snapshot = self.course_snapshot()
            from catalog import aliases_for
            added = build_inbox(paths, list(snapshot), snapshot, recursive=False,
                                aliases=aliases_for(self.root_path()) if self.root_path() else {})
            if target:
                relative = Path(target).relative_to(self.root_path())
                for item in added:
                    item.course = "/".join(relative.parts[:2])
                    item.category = relative.parts[2] if len(relative.parts) >= 3 else None
                    item.reason = "目标来自拖放位置，执行前请核对"
            elif apply:
                for item in added:
                    item.course, item.category = item.suggested_course, item.suggested_category
            if replace:
                self.inbox_items = []
            existing = {item.source for item in self.inbox_items}
            self.inbox_items.extend(item for item in added if item.source not in existing)
            self.render_inbox()
            self.archive_status.setText(f"{len(self.inbox_items)} 个文件")
            if self.inbox_items:
                row = max(0, len(self.inbox_items) - len(added))
                self.inbox_table.setCurrentCell(row, 0)
                self.select_inbox_row(row)
            self.tabs.setCurrentIndex(2)
        except (OSError, ValueError) as exc:
            self.archive_status.setText("不能添加：" + str(exc))

    def render_inbox(self):
        self._loading_inbox = True
        selected_rows = self.selected_inbox_rows()
        snapshot = self.course_snapshot()
        self.inbox_table.blockSignals(True)
        self.inbox_table.setRowCount(len(self.inbox_items))
        self.retry_button.setVisible(any(item.status == "failed" for item in self.inbox_items))
        for row, item in enumerate(self.inbox_items):
            for column in (2, 3, 4):
                old = self.inbox_table.cellWidget(row, column)
                if old:
                    old.hide()
            self.inbox_table.setItem(row, 0, QTableWidgetItem(item.source.name))
            self.inbox_table.item(row, 0).setToolTip(str(item.source) + ("\n" + item.reason if item.reason else ""))
            self.inbox_table.setItem(row, 1, QTableWidgetItem(str(item.size)))
            course = QComboBox()
            course.addItem("需手选", None)
            for key in snapshot:
                course.addItem(key, key)
            course.setCurrentIndex(max(0, course.findData(item.course)))
            course.setToolTip(course.currentText())
            course.currentIndexChanged.connect(lambda _, r=row: self.row_course_changed(r))
            self.inbox_table.setCellWidget(row, 2, course)
            category = QComboBox()
            category.addItem("需手选", None)
            for name in snapshot.get(item.course, []):
                category.addItem(name, name)
            category.setCurrentIndex(max(0, category.findData(item.category)))
            category.setToolTip(category.currentText())
            category.currentIndexChanged.connect(lambda _, r=row: self.row_category_changed(r))
            self.inbox_table.setCellWidget(row, 3, category)
            mode = QComboBox()
            mode.addItem("复制", "copy")
            mode.addItem("移动", "move")
            mode.setCurrentIndex(mode.findData(item.mode))
            mode.currentIndexChanged.connect(lambda _, r=row: self.row_mode_changed(r))
            self.inbox_table.setCellWidget(row, 4, mode)
            for widget in (course, category, mode):
                widget.setEnabled(item.status != "ok")
            self.update_inbox_result(row)
        for row in selected_rows:
            if row < len(self.inbox_items):
                self.inbox_table.selectionModel().select(self.inbox_table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.inbox_table.blockSignals(False)
        self._loading_inbox = False
        self.update_archive_actions()

    def row_course_changed(self, row):
        item = self.inbox_items[row]
        item.course = self.inbox_table.cellWidget(row, 2).currentData()
        item.category = None
        item.status, item.error, item.target = "pending", "", ""
        self.render_inbox()
        self.inbox_table.setCurrentCell(row, 0)
        self.select_inbox_row(row)

    def row_category_changed(self, row):
        self.inbox_items[row].category = self.inbox_table.cellWidget(row, 3).currentData()
        self.inbox_items[row].status, self.inbox_items[row].error, self.inbox_items[row].target = "pending", "", ""
        self.select_inbox_row(row)
        self.update_inbox_result(row)
        self.update_archive_actions()

    def row_mode_changed(self, row):
        self.inbox_items[row].mode = self.inbox_table.cellWidget(row, 4).currentData()
        self.update_archive_actions()

    def select_inbox_row(self, row, *_):
        if self._loading_inbox or not 0 <= row < len(self.inbox_items):
            return
        self._selected_inbox = row
        item = self.inbox_items[row]
        self._loading_inbox = True
        self.source_edit.setText(str(item.source))
        if item.course:
            semester, course = Path(item.course).parts
            self.archive_semester_combo.setCurrentText(semester)
            self.course_combo.setCurrentText(course)
        else:
            self.course_combo.setCurrentIndex(-1)
        if item.category:
            self.category_combo.setCurrentText(item.category)
        else:
            self.category_combo.setCurrentIndex(-1)
        self._loading_inbox = False
        self.update_destination()

    def sync_selected_inbox(self):
        row = self._selected_inbox
        if not 0 <= row < len(self.inbox_items):
            return
        item = self.inbox_items[row]
        if item.status == "ok":
            return
        old_target = (item.course, item.category)
        item.course = (self.archive_semester_combo.currentText() + "/" + self.course_combo.currentText()) if self.course_combo.currentData() else None
        item.category = self.category_combo.currentText() if self.category_combo.currentIndex() > 0 else None
        if (item.course, item.category) != old_target:
            item.status, item.error, item.target = "pending", "", ""
        self.update_inbox_result(row)
        for col, value in ((2, item.course), (3, item.category)):
            widget = self.inbox_table.cellWidget(row, col)
            if widget:
                widget.blockSignals(True)
                if col == 3:
                    widget.clear()
                    widget.addItem("需手选", None)
                    for name in self.course_snapshot().get(item.course, []):
                        widget.addItem(name, name)
                widget.setCurrentIndex(max(0, widget.findData(value)))
                widget.blockSignals(False)

    def selected_inbox_rows(self):
        return sorted(index.row() for index in self.inbox_table.selectionModel().selectedRows())

    def ready_inbox_indices(self):
        selected = set(self.selected_inbox_rows()) if self.execute_scope.currentData() == "selected" else None
        return [i for i, item in enumerate(self.inbox_items)
                if (selected is None or i in selected) and item.course and item.category
                and (item.status == "pending" or (item.status == "skipped" and ("取消" in item.error or "需手选" in item.error)))]

    def update_archive_actions(self, *_):
        if not hasattr(self, "copy_button"):
            return
        ready = self.ready_inbox_indices()
        running = bool(self.file_worker and self.file_worker.isRunning())
        self.copy_button.setText(f"执行 {len(ready)} 项")
        self.copy_button.setEnabled(bool(ready) and not running)
        self.retry_button.setVisible(any(item.status == "failed" for item in self.inbox_items))

    def apply_batch_target(self):
        if self.file_worker and self.file_worker.isRunning():
            return
        course = self.course_combo.currentData()
        if not course or self.category_combo.currentIndex() <= 0:
            self.archive_status.setText("请选择课程和分类")
            return
        key = Path(course).relative_to(self.root_path()).as_posix()
        rows = self.selected_inbox_rows() if self.apply_scope.currentData() == "selected" else range(len(self.inbox_items))
        count = 0
        for row in rows:
            item = self.inbox_items[row]
            if item.status == "ok":
                continue
            item.course, item.category = key, self.category_combo.currentText()
            item.status, item.error, item.target = "pending", "", ""
            count += 1
        self.render_inbox()
        self.archive_status.setText(f"已设置 {count} 项" if count else "请先选中文件")

    def update_inbox_result(self, row):
        item = self.inbox_items[row]
        state = {"pending": "待执行", "ok": "成功", "skipped": "跳过", "failed": "失败"}[item.status]
        if not item.course or not item.category:
            state = "需选目标"
        cell = QTableWidgetItem(state)
        cell.setToolTip(item.error or item.target or state)
        self.inbox_table.setItem(row, 5, cell)
        for column in (2, 3, 4):
            widget = self.inbox_table.cellWidget(row, column)
            if widget:
                widget.setEnabled(item.status != "ok")

    def apply_suggestions(self):
        if self.file_worker and self.file_worker.isRunning():
            return
        for item in self.inbox_items:
            if item.status == "pending":
                if not item.course:
                    item.course = item.suggested_course
                if not item.category and item.course == item.suggested_course:
                    item.category = item.suggested_category
        self.render_inbox()
        if 0 <= self._selected_inbox < len(self.inbox_items):
            self.select_inbox_row(self._selected_inbox)
        unresolved = sum(not item.course or not item.category for item in self.inbox_items if item.status != "ok")
        self.archive_status.setText(f"{len(self.ready_inbox_indices())} 项待执行" + (f" · {unresolved} 项需选目标" if unresolved else ""))

    def clear_inbox(self):
        if self.file_worker and self.file_worker.isRunning():
            return
        self.inbox_items.clear()
        self._selected_inbox = -1
        self.render_inbox()

    def batch_mode_changed(self):
        if self.file_worker and self.file_worker.isRunning():
            return
        mode = "move" if self.move_radio.isChecked() else "copy"
        for item in self.inbox_items:
            if item.status != "ok":
                item.mode = mode
        self.render_inbox()
        self.update_destination()

    def archive_file(self, *, indices=None):
        try:
            if any(worker and worker.isRunning() for worker in (self.file_action_worker,)):
                self.archive_status.setText("请先等待当前操作完成")
                return
            if self.file_worker is not None and self.file_worker.isRunning():
                return
            root = self.root_path()
            if root is None or not self.inbox_items:
                raise ValueError("请选择资料目录并添加待归档文件")
            if indices is None:
                indices = self.ready_inbox_indices()
            if not indices:
                self.archive_status.setText("没有待执行项；失败项请使用“仅重试失败项”")
                return
            self.copy_button.setEnabled(False)
            for widget in (self.source_edit, self.root_edit, self.archive_semester_combo, self.course_combo,
                           self.category_combo, self.move_radio, self.copy_radio):
                widget.setEnabled(False)
            self.inbox_table.setEnabled(False)
            self.apply_scope.setEnabled(False)
            self.execute_scope.setEnabled(False)
            self.cancel_file_button.setEnabled(True)
            self.file_progress.setVisible(True)
            self.file_worker = BatchWorker(self.inbox_items, root, conflict="keep", indices=indices)
            self.file_worker.progress.connect(self.file_progress.setValue)
            self.file_worker.item_done.connect(self.batch_item_done)
            self.file_worker.completed.connect(self.batch_finished)
            self.file_worker.finished.connect(self.file_stopped)
            self.file_worker.start()
        except (OSError, ValueError) as exc:
            self.archive_status.setText("归档失败：" + str(exc))

    def retry_failed(self):
        indices = [index for index, item in enumerate(self.inbox_items) if item.status == "failed"]
        if indices:
            self.archive_file(indices=indices)

    def batch_item_done(self, row, result):
        item = self.inbox_items[row]
        item.status, item.error, item.target = result["status"], result["error"], result["target"]
        if item.target:
            self.last_target = Path(item.target).parent
        self.update_inbox_result(row)
        self.update_archive_actions()

    def batch_finished(self, summary):
        prefix = "移动成功" if self.file_worker.mode == "move" else "复制成功"
        if len({self.inbox_items[i].mode for i in self.file_worker.indices}) > 1:
            prefix = "归档完成"
        if not summary["ok"]:
            prefix = "归档完成"
        unresolved = sum(not item.course or not item.category for item in self.inbox_items if item.status != "ok")
        self.archive_status.setText(f"{prefix} {summary['ok']}、跳过 {summary['skipped']}、失败 {summary['failed']}"
                                   + (f" · {unresolved} 项需选目标" if unresolved else ""))
        self.refresh_browser(preferred=str(self.last_target) if self.last_target else None)

    def file_stopped(self):
        for widget in (self.source_edit, self.root_edit, self.archive_semester_combo, self.course_combo,
                       self.category_combo, self.move_radio, self.copy_radio):
            widget.setEnabled(True)
        self.inbox_table.setEnabled(True)
        self.apply_scope.setEnabled(True)
        self.execute_scope.setEnabled(True)
        self.update_archive_actions()
        self.cancel_file_button.setEnabled(False)
        self.file_progress.setVisible(False)

    def cancel_file(self):
        if self.file_worker is not None:
            self.file_worker.request_cancel()

    def file_dropped_on_tree(self, sources, raw_target):
        root = self.root_path()
        target = Path(raw_target)
        if root is None or not target.is_dir() or not target.resolve().is_relative_to(root.resolve()) or len(target.relative_to(root).parts) < 2:
            self.archive_status.setText("请拖到课程或分类目录，未操作文件")
            return
        self.add_to_inbox(sources if isinstance(sources, list) else [sources], target=target)

    def open_destination(self):
        path = self.target_directory() or self.last_target
        if path and path.is_dir():
            open_with_shell(path, self.statusBar().showMessage)
        else:
            self.archive_status.setText("目标分类文件夹不存在，请先生成目录。")

