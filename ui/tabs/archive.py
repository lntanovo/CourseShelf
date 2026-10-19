"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog,
    QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QMenu,
    QSizePolicy, QTableWidgetItem,
    QRadioButton, QVBoxLayout, QWidget,
)

from organizer import planned_copy_path
from catalog import (disk_categories)
from classifier import suggest
from runtime import (open_with_shell)
from inbox import build_inbox
from tasks import BatchWorker


from ui.widgets import DropFileEdit, Disclosure, InboxTable, SoftComboBox as QComboBox

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
        self.source_edit.textChanged.connect(self.source_text_changed)
        card_layout.addWidget(self.source_edit)
        self.inbox_table = InboxTable()
        self.inbox_table.file_dropped.connect(self.add_to_inbox)
        self.inbox_table.setHorizontalHeaderLabels(["文件", "大小", "课程", "分类", "匹配理由", "方式", "状态"])
        self.inbox_table.setMinimumHeight(165)
        self.inbox_table.setWordWrap(False)
        self.inbox_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inbox_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.inbox_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inbox_table.setShowGrid(False)
        self.inbox_table.verticalHeader().hide()
        self.inbox_table.verticalHeader().setDefaultSectionSize(42)
        self.inbox_table.currentCellChanged.connect(self.select_inbox_row)
        self.inbox_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.inbox_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((180, 65, 210, 105, 150, 80, 170)):
            if column:
                self.inbox_table.setColumnWidth(column, width)
        self.inbox_table.setColumnHidden(4, True)
        card_layout.addWidget(self.inbox_table, 1)
        note = QLabel("课程和分类可直接在行内调整；未匹配的文件需要手选。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        card_layout.addWidget(note)
        layout.addWidget(card, 1)

        details = QFrame()
        details.setObjectName("detailPanel")
        card_layout = QVBoxLayout(details)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(10)
        self.source_label = QLabel("尚未选择文件")
        self.source_label.setObjectName("pathText")
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(self.source_label)
        row = QHBoxLayout()
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
        card_layout.addLayout(row)
        self.suggestion_label = QLabel("选择文件后显示匹配理由。")
        self.suggestion_label.setWordWrap(True)
        card_layout.addWidget(self.suggestion_label)
        self.archive_choice_status = QLabel("请先选择资料库并创建课程目录。")
        self.archive_choice_status.setWordWrap(True)
        self.archive_choice_status.setObjectName("muted")
        card_layout.addWidget(self.archive_choice_status)
        self.destination_label = QLabel("尚未选择目标位置")
        self.destination_label.setObjectName("destination")
        self.destination_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.destination_label.setWordWrap(True)
        self.destination_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(self.destination_label)
        row = QHBoxLayout()
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("同名：保留两个（默认）", "keep")
        self.conflict_combo.addItem("同名：跳过", "skip")
        row.addWidget(self.conflict_combo)
        self.recursive_check = QCheckBox("包含子文件夹")
        row.addWidget(self.recursive_check)
        self.show_reason = QCheckBox("显示匹配理由列")
        self.show_reason.toggled.connect(lambda visible: self.inbox_table.setColumnHidden(4, not visible))
        row.addWidget(self.show_reason)
        row.addStretch()
        card_layout.addLayout(row)
        alias = self._button("把本次选择记为别名…", self.remember_alias_ui)
        alias.setObjectName("quiet")
        card_layout.addWidget(alias, alignment=Qt.AlignmentFlag.AlignLeft)
        self.archive_details = Disclosure("选中项详情与进阶选项", details)
        layout.addWidget(self.archive_details)
        # Keep the disclosure control reachable while its content scrolls.
        outer.addWidget(self.archive_details.toggle)
        self.archive_details.toggle.toggled.connect(
            lambda expanded: QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(details, 0, 12)) if expanded else None)

        footer = QFrame()
        footer.setObjectName("actionBar")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 12, 18, 12)
        row = QHBoxLayout()
        self.copy_radio = QRadioButton("复制 · 保留来源")
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
        self.archive_status = QLabel("默认复制，同名保留两个。确认课程后再执行。")
        self.source_edit.rejected.connect(self.archive_status.setText)
        self.archive_status.setWordWrap(True)
        self.archive_status.setObjectName("muted")
        result_row.addWidget(self.archive_status, 1)
        open_target = self._button("打开目标文件夹", self.open_destination)
        open_target.setObjectName("quiet")
        result_row.addWidget(open_target)
        footer_layout.addLayout(result_row)
        outer.addWidget(footer)
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
            self.archive_choice_status.setText(f"已找到 {len(courses)} 门磁盘上的课程，可选择分类复制资料。")
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
        self.category_combo.addItems(categories)
        self.category_combo.setEnabled(bool(categories))
        index = self.category_combo.findText(selected)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)
        self.update_destination()
        self.refresh_manage_categories()

    def target_directory(self) -> Path | None:
        root = self.root_path()
        course_data = self.course_combo.currentData()
        category = self.category_combo.currentText()
        if root and course_data and category:
            course_path = Path(course_data)
            target = course_path / category
            if (not course_path.is_symlink() and course_path.is_dir() and not target.is_symlink()
                    and target.is_dir() and target.resolve().is_relative_to(root.resolve())):
                return target
        return None

    def update_destination(self, *_):
        source_text = self.source_edit.text().strip()
        self.source_label.setText("来源文件：" + source_text if source_text else "来源文件：尚未选择")
        if not self._loading_inbox:
            self.sync_selected_inbox()
        self.copy_button.setText(f"执行 {len(self.inbox_items)} 项")
        destination_dir = self.target_directory()
        if destination_dir is None:
            self.destination_label.setText("最终目标文件：请先选择资料目录并生成课程分类")
        elif not source_text:
            self.destination_label.setText("目标文件夹：" + str(destination_dir) + "\n请选择来源文件以预览最终文件名。")
        else:
            proposed = planned_copy_path(Path(source_text), destination_dir)
            self.destination_label.setText("最终目标文件：" + str(proposed))

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
        self.add_to_inbox([raw], replace=True, apply=True)
        self.suggest_target()

    def add_to_inbox(self, paths, *, replace=False, apply=False, target=None):
        if self.file_worker and self.file_worker.isRunning():
            return
        try:
            snapshot = self.course_snapshot()
            from catalog import aliases_for
            added = build_inbox(paths, list(snapshot), snapshot, recursive=self.recursive_check.isChecked(),
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
            if self.inbox_items:
                row = max(0, len(self.inbox_items) - len(added))
                self.inbox_table.setCurrentCell(row, 0)
                self.select_inbox_row(row)
            self.tabs.setCurrentIndex(2)
        except (OSError, ValueError) as exc:
            self.archive_status.setText("不能添加：" + str(exc))

    def render_inbox(self):
        self._loading_inbox = True
        snapshot = self.course_snapshot()
        self.inbox_table.blockSignals(True)
        self.inbox_table.setRowCount(len(self.inbox_items))
        self.retry_button.setVisible(any(item.status == "failed" for item in self.inbox_items))
        for row, item in enumerate(self.inbox_items):
            self.inbox_table.setItem(row, 0, QTableWidgetItem(item.source.name))
            self.inbox_table.item(row, 0).setToolTip(str(item.source))
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
            self.inbox_table.setItem(row, 4, QTableWidgetItem(item.reason))
            self.inbox_table.item(row, 4).setToolTip(item.reason)
            mode = QComboBox()
            mode.addItem("复制", "copy")
            mode.addItem("移动", "move")
            mode.setCurrentIndex(mode.findData(item.mode))
            mode.currentIndexChanged.connect(lambda _, r=row: self.row_mode_changed(r))
            self.inbox_table.setCellWidget(row, 5, mode)
            state = {"pending": "待执行", "ok": "成功", "skipped": "跳过", "failed": "失败"}[item.status]
            if not item.course or not item.category:
                state += " · 需手选"
            self.inbox_table.setItem(row, 6, QTableWidgetItem(state + (" · " + item.error if item.error else "")))
            self.inbox_table.item(row, 6).setToolTip(item.error or state)
        self.inbox_table.blockSignals(False)
        self._loading_inbox = False
        self.copy_button.setText(f"执行 {len(self.inbox_items)} 项")

    def row_course_changed(self, row):
        item = self.inbox_items[row]
        item.course = self.inbox_table.cellWidget(row, 2).currentData()
        item.category = None
        self.render_inbox()
        self.inbox_table.setCurrentCell(row, 0)
        self.select_inbox_row(row)

    def row_category_changed(self, row):
        self.inbox_items[row].category = self.inbox_table.cellWidget(row, 3).currentData()
        self.select_inbox_row(row)

    def row_mode_changed(self, row):
        self.inbox_items[row].mode = self.inbox_table.cellWidget(row, 5).currentData()

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
        self.suggestion_label.setText("文件名建议：" + item.reason)
        self._loading_inbox = False
        self.update_destination()

    def sync_selected_inbox(self):
        row = self._selected_inbox
        if not 0 <= row < len(self.inbox_items):
            return
        item = self.inbox_items[row]
        item.course = (self.archive_semester_combo.currentText() + "/" + self.course_combo.currentText()) if self.course_combo.currentData() else None
        item.category = self.category_combo.currentText() or None
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

    def apply_suggestions(self):
        if self.file_worker and self.file_worker.isRunning():
            return
        for item in self.inbox_items:
            if item.status != "ok" and item.suggested_course and item.suggested_category:
                item.course, item.category = item.suggested_course, item.suggested_category
        self.render_inbox()
        if 0 <= self._selected_inbox < len(self.inbox_items):
            self.select_inbox_row(self._selected_inbox)

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
            item.mode = mode
        self.render_inbox()
        self.update_destination()

    def archive_file(self, *, indices=None):
        try:
            if any(worker and worker.isRunning() for worker in (self.undo_worker, self.file_action_worker)):
                self.archive_status.setText("请先等待撤销结束")
                return
            if self.file_worker is not None and self.file_worker.isRunning():
                return
            root = self.root_path()
            if root is None or not self.inbox_items:
                raise ValueError("请选择资料目录并添加待归档文件")
            if indices is None:
                indices = [i for i, item in enumerate(self.inbox_items) if item.status in {"pending", "skipped"}]
            if not indices:
                self.archive_status.setText("没有待执行项；失败项请使用“仅重试失败项”")
                return
            self.copy_button.setEnabled(False)
            for widget in (self.source_edit, self.root_edit, self.archive_semester_combo, self.course_combo,
                           self.category_combo, self.move_radio, self.copy_radio, self.conflict_combo):
                widget.setEnabled(False)
            self.inbox_table.setEnabled(False)
            self.cancel_file_button.setEnabled(True)
            self.file_progress.setVisible(True)
            self.file_worker = BatchWorker(self.inbox_items, root, conflict=self.conflict_combo.currentData(), indices=indices)
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
        self.render_inbox()

    def batch_finished(self, summary):
        prefix = "移动成功" if self.file_worker.mode == "move" else "复制成功"
        if not summary["ok"]:
            prefix = "归档完成"
        self.archive_status.setText(f"{prefix} {summary['ok']}、跳过 {summary['skipped']}、失败 {summary['failed']}")
        self.refresh_browser(preferred=str(self.last_target) if self.last_target else None)

    def file_stopped(self):
        for widget in (self.source_edit, self.root_edit, self.archive_semester_combo, self.course_combo,
                       self.category_combo, self.move_radio, self.copy_radio, self.conflict_combo):
            widget.setEnabled(True)
        self.copy_button.setEnabled(True)
        self.inbox_table.setEnabled(True)
        self.cancel_file_button.setEnabled(False)
        self.file_progress.setVisible(False)

    def cancel_file(self):
        if self.file_worker is not None:
            self.file_worker.request_cancel()

    def suggest_target(self, *_):
        if self._suggesting:
            return
        source = Path(self.source_edit.text().strip())
        if not source.is_file():
            self.suggestion_label.setText("文件名建议：请选择存在的普通文件。")
            self.update_destination()
            return
        self._suggesting = True
        try:
            courses = [self.course_combo.itemText(i) for i in range(self.course_combo.count()) if self.course_combo.itemData(i)]
            from catalog import aliases_for
            semester = self.archive_semester_combo.currentText()
            aliases = {Path(key).name: value for key, value in aliases_for(self.root_path()).items()
                       if Path(key).parts[0] == semester} if self.root_path() else {}
            result = suggest(source.name, courses, aliases=aliases)
            if result.course and result.confidence == "high":
                self.course_combo.setCurrentText(result.course)
            else:
                self.course_combo.setCurrentIndex(-1)
            categories = [self.category_combo.itemText(i) for i in range(self.category_combo.count())]
            result = suggest(source.name, courses, categories, aliases=aliases)
            if result.category:
                self.category_combo.setCurrentText(result.category)
            self.suggestion_label.setText("文件名建议：" + result.reason + "。可手动修改目标。")
        finally:
            self._suggesting = False
            self.update_destination()

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

