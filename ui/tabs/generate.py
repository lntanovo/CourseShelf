"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations


from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QWidget, QTreeWidgetItem, QStyle,
)

from organizer import build_plan, safe_name
from catalog import create_plan, plan_paths
from ui.widgets import DirectoryPreview, SoftComboBox as QComboBox



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
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.file_action_worker)):
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

