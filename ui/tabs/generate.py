"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QInputDialog, QListWidget, QMessageBox, QWidget, QTreeWidgetItem, QStyle,
)

from organizer import build_plan, safe_name
from catalog import (add_category, create_plan,
                     disk_categories, import_course, is_managed, missing_paths, plan_paths,
                     restore_defaults, restore_missing)
from dialogs import confirm
from ui.widgets import Disclosure, DirectoryPreview, SoftComboBox as QComboBox



class GenerateMixin:
    def _make_generate_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        self.plan_common_categories = []
        self.plan_course_categories = {}
        card, card_layout = self._card("设置学期并预览")
        card_layout.addWidget(QLabel("学期名称"))
        self.semester_edit = QLineEdit()
        self.semester_edit.setPlaceholderText("例如 2026秋季学期")
        self.semester_edit.textChanged.connect(self.invalidate_preview)
        card_layout.addWidget(self.semester_edit)
        row = QHBoxLayout()
        row.addWidget(self._button("预览将创建的目录", self.show_preview))
        row.addWidget(self._button("确认生成目录", self.generate, True))
        row.addStretch()
        card_layout.addLayout(row)
        categories = QHBoxLayout()
        self.plan_category_name = QComboBox()
        self.plan_category_name.setEditable(True)
        self.plan_category_name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.plan_category_name.addItems(["课设", "实验", "论文", "参考资料", "课堂笔记"])
        self.plan_category_name.setCurrentIndex(-1)
        self.plan_category_name.setPlaceholderText("输入或选择新增分类")
        self.plan_scope = QComboBox()
        self.plan_scope.addItem("全部课程", None)
        categories.addWidget(self.plan_category_name, 2)
        categories.addWidget(self.plan_scope, 2)
        categories.addWidget(self._button("加入预览", self.add_plan_category))
        categories.addWidget(self._button("清空新增分类", self.clear_plan_categories))
        card_layout.addLayout(categories)
        self.preview = DirectoryPreview()
        self.preview.setHeaderLabels(["文件夹", "状态"])
        self.preview.setColumnWidth(0, 550)
        self.preview.setMinimumHeight(220)
        card_layout.addWidget(self.preview)
        self.generate_status = QLabel("")
        self.generate_status.setWordWrap(True)
        card_layout.addWidget(self.generate_status)
        layout.addWidget(card)
        manage, manage_layout = self._card("管理当前课程分类")
        self.manage_course_combo = QComboBox()
        self.manage_course_combo.currentIndexChanged.connect(self.refresh_manage_categories)
        manage_layout.addWidget(self.manage_course_combo)
        self.manage_path = QLabel("尚未选择课程")
        self.manage_path.setWordWrap(True)
        manage_layout.addWidget(self.manage_path)
        self.manage_categories = QListWidget()
        self.manage_categories.setMinimumHeight(110)
        manage_layout.addWidget(self.manage_categories)
        buttons = QHBoxLayout()
        for label, method in (("添加分类", self.add_category_ui), ("重命名分类", self.rename_category_ui),
                              ("移至回收站", self.delete_category_ui)):
            buttons.addWidget(self._button(label, method))
        manage_layout.addLayout(buttons)
        buttons = QHBoxLayout()
        for label, method in (("恢复默认分类", self.restore_defaults_ui), ("纳入管理", self.import_course_ui)):
            buttons.addWidget(self._button(label, method))
        buttons.addStretch()
        manage_layout.addLayout(buttons)
        manage_layout.addWidget(self._button("编辑课程别名", self.edit_aliases_ui))
        self.manage_details = Disclosure("管理分类与课程别名", manage)
        layout.addWidget(self.manage_details)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：整理资料  →", self.advance_to_archive, True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def invalidate_preview(self, *_):
        if hasattr(self, "preview"):
            self.preview.clear()
            self.generate_status.clear()
            self.refresh_plan_scope()

    def refresh_plan_scope(self):
        if not hasattr(self, "plan_scope"):
            return
        selected = self.plan_scope.currentData()
        self.plan_scope.blockSignals(True)
        self.plan_scope.clear()
        self.plan_scope.addItem("全部课程", None)
        for name in dict.fromkeys(self.course_names()):
            if name.strip():
                self.plan_scope.addItem(name, name)
        self.plan_scope.setCurrentIndex(max(0, self.plan_scope.findData(selected)))
        self.plan_scope.blockSignals(False)

    def preview_extras(self):
        return {safe_name(name): list(dict.fromkeys(self.plan_common_categories + self.plan_course_categories.get(name, [])))
                for name in self.course_names() if name.strip()}

    def add_plan_category(self):
        name = self.plan_category_name.currentText().strip()
        if not name or safe_name(name) != name:
            self.generate_status.setText("请输入有效分类名称")
            return
        if not self.course_names():
            self.generate_status.setText("请先添加课程")
            return
        scope = self.plan_scope.currentData()
        values = self.plan_common_categories if scope is None else self.plan_course_categories.setdefault(scope, [])
        if name.casefold() not in {value.casefold() for value in values}:
            values.append(name)
        self.show_preview()

    def clear_plan_categories(self):
        self.plan_common_categories.clear()
        self.plan_course_categories.clear()
        self.show_preview()

    def plan(self):
        root = self.root_path()
        if root is None:
            raise ValueError("请先选择现有的资料总目录")
        return build_plan(root, self.semester_edit.text(), self.course_names())

    def show_preview(self):
        self.preview.clear()
        try:
            root = self.root_path()
            if root is None:
                raise ValueError("请先选择现有的资料总目录")
            semester, items, paths = plan_paths(root, self.semester_edit.text(), self.course_names(), extra_categories=self.preview_extras())
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            def node(path, parent=None):
                linked = path.is_symlink() or path.is_junction()
                state = "冲突" if linked or (path.exists() and not path.is_dir()) else "已有" if path.is_dir() else "新建"
                item = QTreeWidgetItem([path.name, state])
                item.setIcon(0, icon)
                item.setToolTip(0, str(path))
                if parent is None:
                    self.preview.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                return item
            top = node(semester)
            for course, names in items:
                parent = node(course, top)
                for name in names:
                    node(course / name, parent)
            top.setExpanded(True)
            self.generate_status.setText(f"{len(items)} 门课程 · {len(paths)} 个目录")
            return True
        except (OSError, ValueError) as exc:
            self.generate_status.setText("无法预览：" + str(exc))
            return False

    def generate(self):
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            self.generate_status.setText("请等待当前操作完成")
            return False
        if not self.show_preview():
            return
        try:
            root = self.root_path()
            semester_path, _ = self.plan()
            created, existing, failures, _ = create_plan(root, self.semester_edit.text(), self.course_names(), extra_categories=self.preview_extras())
            message = f"创建 {created}，已存在 {existing}，失败 {len(failures)}"
            if failures:
                message += "\n" + "\n".join(failures)
            self.generate_status.setText(message)
            self.refresh_targets(preferred=semester_path.name)
            self.refresh_browser(preferred=str(semester_path))
            return not failures
        except (OSError, ValueError) as exc:
            self.generate_status.setText("生成失败：" + str(exc))
            return False

    def advance_to_archive(self):
        if not self.show_preview():
            return
        root = self.root_path()
        _, _, paths = plan_paths(root, self.semester_edit.text(), self.course_names(), extra_categories=self.preview_extras())
        blocked = [p for p in paths if p.is_symlink() or (p.exists() and not p.is_dir())]
        if blocked:
            self.generate_status.setText("目录被同名文件或链接阻挡：" + str(blocked[0]))
            return
        pending = [p for p in paths if not p.is_dir()]
        if pending:
            box = QMessageBox(self)
            box.setWindowTitle("确认创建目录")
            box.setText(f"资料总目录：{root}\n学期：{self.semester_edit.text()}\n待建目录：{len(pending)} 个")
            create = box.addButton("创建并继续", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("返回检查", QMessageBox.ButtonRole.RejectRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() != create or not self.generate():
                return
        self.tabs.setCurrentIndex(2)

    def _managed_course(self) -> tuple[Path, str, str] | None:
        root = self.root_path()
        raw = self.manage_course_combo.currentData()
        if root and raw:
            path = Path(raw)
            if path.is_dir() and path.is_relative_to(root) and len(path.relative_to(root).parts) == 2:
                return root, path.parent.name, path.name
        return None

    def refresh_manage_categories(self, *_):
        selected = self.manage_course_combo.currentData()
        self.manage_course_combo.blockSignals(True)
        self.manage_course_combo.clear()
        root = self.root_path()
        if root:
            for key in self.course_snapshot():
                self.manage_course_combo.addItem(key, str(root / key))
        index = self.manage_course_combo.findData(selected)
        if index >= 0:
            self.manage_course_combo.setCurrentIndex(index)
        self.manage_course_combo.blockSignals(False)
        self.manage_categories.clear()
        choice = self._managed_course()
        if choice is None:
            self.manage_path.setText("尚未选择课程")
            return
        root, semester, course = choice
        path = root / semester / course
        try:
            managed = is_managed(root, semester, course)
            names = disk_categories(root, semester, course)
            self.manage_path.setText(f"{path}\n" + ("已纳入管理" if managed else "现有目录尚未纳入管理"))
            self.manage_categories.addItems(names)
        except (OSError, ValueError) as exc:
            self.manage_path.setText("课程目录不可用：" + str(exc))

    def _category_action(self, operation):
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            self.statusBar().showMessage("请先等待归档或撤销结束")
            return
        choice = self._managed_course()
        if choice is None:
            QMessageBox.warning(self, "请选择课程", "请先在目录树或课程下拉框中选择课程。")
            return
        try:
            operation(*choice)
            self.invalidate_preview()
            self.refresh_browser()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "分类操作失败", str(exc))

    def import_course_ui(self):
        def action(root, semester, course):
            path = root / semester / course
            names = disk_categories(root, semester, course)
            preview = "\n".join("  • " + str(path / name) for name in names) or "  （当前没有分类子目录）"
            if QMessageBox.question(self, "纳入管理", f"登记现有课程及以下分类？\n{path}\n{preview}\n不会修改已有文件。", defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                import_course(root, semester, course)
        self._category_action(action)

    def add_category_ui(self):
        def action(root, semester, course):
            name, ok = QInputDialog.getText(self, "添加分类", "分类名称")
            if ok and name.strip() and QMessageBox.question(self, "确认创建", "创建目录：\n" + str(root / semester / course / name.strip()), defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                add_category(root, semester, course, name)
        self._category_action(action)

    def rename_category_ui(self):
        def action(root, semester, course):
            old = self.manage_categories.currentItem()
            if old is None:
                raise ValueError("请先选择一个分类")
            name, ok = QInputDialog.getText(self, "重命名分类", "新名称", text=old.text())
            if ok and name.strip() and QMessageBox.question(self, "确认重命名", f"{root / semester / course / old.text()}\n→ {root / semester / course / name.strip()}", defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.start_category_action((root, semester, course), old.text(), name)
        self._category_action(action)

    def start_category_action(self, choice, category, name=None):
        from tasks import CategoryWorker
        self.file_action_worker = CategoryWorker(choice, category, name)
        self.statusBar().showMessage("正在后台校验分类内文件的归档记录与内容…")
        self.file_action_worker.completed.connect(self.statusBar().showMessage)
        self.file_action_worker.failed.connect(self.statusBar().showMessage)
        self.file_action_worker.finished.connect(self.invalidate_preview)
        self.file_action_worker.finished.connect(self.request_refresh)
        self.file_action_worker.start()

    def delete_category_ui(self):
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            self.statusBar().showMessage("请先等待归档或撤销结束")
            return
        from tasks import CountWorker
        choice = self._managed_course()
        item = self.manage_categories.currentItem()
        if choice is None or item is None:
            self.statusBar().showMessage("请先选择一个受管分类")
            return
        root, semester, course = choice
        name = item.text()
        path = root / semester / course / name
        self.statusBar().showMessage("正在后台统计分类内容…")
        worker = CountWorker(path)
        self._directory_workers.append(worker)
        worker.completed.connect(lambda counts: self.confirm_trash_category(choice, name, counts))
        worker.failed.connect(self.statusBar().showMessage)
        worker.finished.connect(lambda w=worker: self._directory_stopped(w))
        worker.start()

    def confirm_trash_category(self, choice, name, counts):
        if getattr(self, "_closing", False):
            return
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            self.statusBar().showMessage("归档或撤销正在进行，请稍后重新统计")
            return
        root, semester, course = choice
        files, directories = counts
        path = root / semester / course / name
        if confirm(self, "移至回收站", f"将整个分类目录移至回收站？\n{path}\n包含 {files} 个文件、{directories} 个子目录。"):
            self.start_category_action(choice, name)

    def restore_defaults_ui(self):
        def action(root, semester, course):
            if confirm(self, "恢复默认分类", f"在 {root / semester / course} 下补建缺失的默认分类？"):
                restore_defaults(root, semester, course)
        self._category_action(action)

    def refresh_missing(self):
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

    def edit_aliases_ui(self):
        from catalog import aliases_for, set_aliases
        def action(root, semester, course):
            values = aliases_for(root).get(semester + "/" + course, [])
            text, ok = QInputDialog.getMultiLineText(self, "编辑课程别名", "每行一个别名。共享别名会导致待手选；不会自动学习。", "\n".join(values))
            if ok and confirm(self, "保存课程别名", f"为 {course} 保存以下别名？\n{text or '（清空）'}", "保存别名"):
                set_aliases(root, semester, course, [line.strip() for line in text.splitlines() if line.strip()])
        self._category_action(action)

    def remember_alias_ui(self):
        from catalog import aliases_for, set_aliases
        choice = self._managed_course()
        course_data = self.course_combo.currentData()
        if not choice or not course_data:
            self.archive_status.setText("请先为选中行手动选择课程")
            return
        root = self.root_path()
        path = Path(course_data)
        semester, course = path.parent.name, path.name
        alias, ok = QInputDialog.getText(self, "把本次选择记为别名", f"请输入 {course} 的简称（仅本次显式保存）：")
        if ok and alias.strip() and confirm(self, "保存别名", f"将“{alias.strip()}”记为“{course}”的别名？", "保存别名"):
            try:
                values = aliases_for(root).get(semester + "/" + course, [])
                set_aliases(root, semester, course, [*values, alias.strip()])
                self.archive_status.setText("课程别名已保存；不会自动记住其他选择")
            except (OSError, ValueError) as exc:
                self.archive_status.setText(str(exc))

