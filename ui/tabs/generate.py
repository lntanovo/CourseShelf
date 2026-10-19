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

class GenerateMixin:
    def _make_generate_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        note = QLabel("预览只读；确认后才建立目录。每门课程可独立管理分类。")
        note.setWordWrap(True)
        layout.addWidget(note)
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
        card_layout.addWidget(QLabel("预览：学期 / 课程 / 课件、作业、复习资料、其他"))
        self.preview = QListWidget()
        self.preview.setMinimumHeight(260)
        card_layout.addWidget(self.preview)
        self.generate_status = QLabel("请先核对课程，并选择一个已有的资料总目录。")
        self.generate_status.setWordWrap(True)
        card_layout.addWidget(self.generate_status)
        layout.addWidget(card)
        manage, manage_layout = self._card("管理当前课程分类")
        manage_layout.addWidget(QLabel("选择右侧目录树中的课程或分类，也可使用第 ③ 步的课程下拉框。"))
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
        layout.addWidget(manage)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：整理资料  →", self.advance_to_archive, True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def invalidate_preview(self, *_):
        if hasattr(self, "preview"):
            self.preview.clear()
            self.generate_status.setText("输入已变化，请重新预览当前目录计划。")

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
            _, _, paths = plan_paths(root, self.semester_edit.text(), self.course_names())
            self.preview.addItems([f"{'已存在' if path.is_dir() and not path.is_symlink() else '待创建'}  ·  {path}" for path in paths])
            self.generate_status.setText(f"预览 {len(paths)} 个目录。已有目录会复用，不会覆盖其中的文件。")
            return True
        except (OSError, ValueError) as exc:
            self.generate_status.setText("无法预览：" + str(exc))
            return False

    def generate(self):
        if not self.show_preview():
            return
        try:
            root = self.root_path()
            semester_path, _ = self.plan()
            created, existing, failures, _ = create_plan(root, self.semester_edit.text(), self.course_names())
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
        _, _, paths = plan_paths(root, self.semester_edit.text(), self.course_names())
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
        if root is None:
            return None
        current = self.folder_tree.currentItem()
        if current is not None:
            path = Path(current.data(0, Qt.ItemDataRole.UserRole))
            if path.is_dir() and path.resolve().is_relative_to(root.resolve()):
                relative = path.relative_to(root)
                if len(relative.parts) >= 2:
                    return root, relative.parts[0], relative.parts[1]
        course_data = self.course_combo.currentData()
        if course_data:
            path = Path(course_data)
            return root, path.parent.name, path.name
        return None

    def refresh_manage_categories(self):
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
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker)):
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
                rename_category(root, semester, course, old.text(), name)
        self._category_action(action)

    def delete_category_ui(self):
        def action(root, semester, course):
            item = self.manage_categories.currentItem()
            if item is None:
                raise ValueError("请先选择一个分类")
            path = root / semester / course / item.text()
            files, dirs = count_contents(path)
            if confirm(self, "移至回收站", f"将整个分类目录移至 Windows 回收站？\n{path}\n包含 {files} 个文件、{dirs} 个子目录。"):
                trash_category(root, semester, course, item.text())
        self._category_action(action)

    def restore_defaults_ui(self):
        def action(root, semester, course):
            if confirm(self, "恢复默认分类", f"在 {root / semester / course} 下补建缺失的默认分类？"):
                restore_defaults(root, semester, course)
        self._category_action(action)

    def refresh_missing(self):
        root = self.root_path()
        self.missing_combo.clear()
        if root is None:
            return
        try:
            from catalog import load_catalog
            data = load_catalog(root)
            if data.get("_read_only"):
                self.missing_label.setText(data["_warning"])
                return
            missing = missing_paths(root)
        except (OSError, ValueError) as exc:
            self.missing_label.setText("管理记录不可读取；仍可浏览磁盘文件：" + str(exc))
            return
        for path in missing:
            self.missing_combo.addItem(str(path), str(path))
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

