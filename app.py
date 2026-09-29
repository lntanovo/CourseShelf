"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

import os
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog,
    QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import (
    CATEGORIES, build_plan, copy_unique, create_directories, extract_candidates,
    load_settings, local_ocr, planned_copy_path, preview_paths, save_root,
    save_settings,
)


class OcrWorker(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, image: Path):
        super().__init__()
        self.image = image

    def run(self):
        try:
            self.completed.emit(local_ocr(self.image))
        except Exception as exc:
            self.failed.emit(str(exc))


class DropFileEdit(QLineEdit):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and len(event.mimeData().urls()) == 1:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        url = event.mimeData().urls()[0]
        if url.isLocalFile():
            self.file_dropped.emit(url.toLocalFile())
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("学习资料整理")
        self.resize(1380, 860)
        self.setMinimumSize(1040, 680)
        self.image_path: Path | None = None
        self.worker: OcrWorker | None = None
        self.last_target: Path | None = None
        self.current_directory: Path | None = None
        self.tree_items: dict[Path, QTreeWidgetItem] = {}

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        heading = QLabel("学习资料整理")
        heading.setObjectName("heading")
        outer.addWidget(heading)
        description = QLabel("课表识别 → 核对课程 → 生成目录 → 复制资料。所有资料都保存在你选择的本机文件夹中。")
        description.setObjectName("subtitle")
        outer.addWidget(description)
        outer.addWidget(self._make_root_card())

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        horizontal.setChildrenCollapsible(False)
        outer.addWidget(horizontal, 1)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(470)
        self.tabs.addTab(self._make_ocr_tab(), "1  识别与核对")
        self.tabs.addTab(self._make_generate_tab(), "2  生成目录")
        self.tabs.addTab(self._make_archive_tab(), "3  整理资料")
        horizontal.addWidget(self.tabs)
        horizontal.addWidget(self._make_browser())
        horizontal.setSizes([590, 710])
        self.setStyleSheet(STYLE)

        settings = load_settings()
        remembered = settings.get("root")
        if isinstance(remembered, str) and remembered:
            if Path(remembered).is_dir():
                self.root_edit.setText(remembered)
                self.root_changed(save=False, preferred=settings.get("last_viewed"))
            else:
                self.root_status.setText("上次使用的资料目录已失效，请选择现有文件夹：" + remembered)
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "资料目录不可用", "上次使用的资料目录已不存在，请重新选择现有文件夹。\n" + remembered))
        else:
            self.root_status.setText("尚未选择资料总目录。请选择一个已有的普通文件夹。")
        self.refresh_targets()

    @staticmethod
    def _button(text: str, callback, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
        card = QGroupBox(title)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(10)
        return card, layout

    @staticmethod
    def _scroll_content() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background-color: #f3f6fa;")
        body = QWidget()
        body.setObjectName("tabBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(14)
        scroll.setWidget(body)
        return scroll, layout

    def _make_root_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("rootCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        row = QHBoxLayout()
        label = QLabel("当前资料总目录")
        label.setObjectName("sectionTitle")
        row.addWidget(label)
        row.addStretch()
        row.addWidget(self._button("选择 / 更换文件夹", self.choose_root))
        row.addWidget(self._button("在资源管理器中打开", self.open_root))
        layout.addLayout(row)
        self.root_edit = QLineEdit()
        self.root_edit.setObjectName("rootPath")
        self.root_edit.setPlaceholderText("请选择已有的本机文件夹；也可粘贴完整路径并按 Enter")
        self.root_edit.editingFinished.connect(self.root_changed)
        layout.addWidget(self.root_edit)
        self.root_status = QLabel()
        self.root_status.setObjectName("muted")
        self.root_status.setWordWrap(True)
        layout.addWidget(self.root_status)
        return card

    def _make_ocr_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        note = QLabel("先选课表截图并在本机识别，再逐项核对课程名。识别有误时可直接修改。")
        note.setWordWrap(True)
        layout.addWidget(note)

        image_card, image_layout = self._card("导入课表图片")
        self.image_label = QLabel("尚未选择图片")
        self.image_label.setObjectName("pathText")
        self.image_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.image_label.setWordWrap(True)
        image_layout.addWidget(self.image_label)
        self.thumbnail = QLabel("支持 PNG / JPG / JPEG")
        self.thumbnail.setObjectName("imagePreview")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumHeight(154)
        image_layout.addWidget(self.thumbnail)
        row = QHBoxLayout()
        row.addWidget(self._button("选择课表图片", self.choose_image))
        self.ocr_button = self._button("开始本地识别", self.start_ocr, True)
        self.ocr_button.setEnabled(False)
        row.addWidget(self.ocr_button)
        row.addStretch()
        image_layout.addLayout(row)
        self.ocr_progress = QProgressBar()
        self.ocr_progress.setTextVisible(False)
        self.ocr_progress.setVisible(False)
        image_layout.addWidget(self.ocr_progress)
        self.ocr_status = QLabel("OCR 尚未运行")
        self.ocr_status.setWordWrap(True)
        image_layout.addWidget(self.ocr_status)
        layout.addWidget(image_card)

        course_card, course_layout = self._card("核对课程名称")
        self.course_hint = QLabel("当前没有课程。识别课表或手动添加后即可生成目录。")
        self.course_hint.setWordWrap(True)
        course_layout.addWidget(self.course_hint)
        self.courses_list = QListWidget()
        self.courses_list.setMinimumHeight(190)
        self.courses_list.itemChanged.connect(self.refresh_course_hint)
        course_layout.addWidget(self.courses_list)
        row = QHBoxLayout()
        self.new_course = QLineEdit()
        self.new_course.setPlaceholderText("输入新课程名称")
        self.new_course.returnPressed.connect(self.add_course)
        row.addWidget(self.new_course, 1)
        row.addWidget(self._button("添加", self.add_course))
        course_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self._button("修改选中课程", self.edit_course))
        row.addWidget(self._button("删除选中课程", self.delete_course))
        row.addStretch()
        course_layout.addLayout(row)
        layout.addWidget(course_card)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：生成目录  →", lambda: self.tabs.setCurrentIndex(1), True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def _make_generate_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        note = QLabel("目录会直接建立在窗口顶部显示的资料总目录中。每门课程固定包含四个分类。")
        note.setWordWrap(True)
        layout.addWidget(note)
        card, card_layout = self._card("设置学期并预览")
        card_layout.addWidget(QLabel("学期名称"))
        self.semester_edit = QLineEdit()
        self.semester_edit.setPlaceholderText("例如 2026秋季学期")
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
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：整理资料  →", lambda: self.tabs.setCurrentIndex(2), True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def _make_archive_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        note = QLabel("选择一个文件和磁盘上已有的课程分类。只复制，不移动或覆盖源文件。")
        note.setWordWrap(True)
        layout.addWidget(note)
        card, card_layout = self._card("选择来源文件")
        row = QHBoxLayout()
        self.source_edit = DropFileEdit()
        self.source_edit.setPlaceholderText("选择或拖入一个本地文件")
        self.source_edit.file_dropped.connect(self.source_edit.setText)
        self.source_edit.textChanged.connect(self.update_destination)
        row.addWidget(self.source_edit, 1)
        row.addWidget(self._button("浏览文件", self.choose_file))
        card_layout.addLayout(row)
        self.source_label = QLabel("来源：尚未选择文件")
        self.source_label.setObjectName("pathText")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_label.setWordWrap(True)
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(self.source_label)
        layout.addWidget(card)

        card, card_layout = self._card("选择目标位置")
        row = QHBoxLayout()
        semester_column = QVBoxLayout()
        semester_column.addWidget(QLabel("学期"))
        self.archive_semester_combo = QComboBox()
        self.archive_semester_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.archive_semester_combo.currentIndexChanged.connect(self.refresh_courses)
        semester_column.addWidget(self.archive_semester_combo)
        row.addLayout(semester_column, 1)
        course_column = QVBoxLayout()
        course_column.addWidget(QLabel("课程"))
        self.course_combo = QComboBox()
        self.course_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.course_combo.currentIndexChanged.connect(self.update_destination)
        course_column.addWidget(self.course_combo)
        row.addLayout(course_column, 1)
        card_layout.addLayout(row)
        card_layout.addWidget(QLabel("分类"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        self.category_combo.currentIndexChanged.connect(self.update_destination)
        card_layout.addWidget(self.category_combo)
        self.archive_choice_status = QLabel("请先选择资料总目录并生成课程分类。")
        self.archive_choice_status.setWordWrap(True)
        card_layout.addWidget(self.archive_choice_status)
        self.destination_label = QLabel("最终目标文件：请先选择来源、学期和课程")
        self.destination_label.setObjectName("destination")
        self.destination_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.destination_label.setWordWrap(True)
        self.destination_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(self.destination_label)
        row = QHBoxLayout()
        self.copy_button = self._button("确认复制到此位置", self.archive_file, True)
        row.addWidget(self.copy_button)
        row.addWidget(self._button("打开目标文件夹", self.open_destination))
        row.addStretch()
        card_layout.addLayout(row)
        self.archive_status = QLabel("复制成功后，右侧文件列表会立即显示结果。")
        self.archive_status.setWordWrap(True)
        card_layout.addWidget(self.archive_status)
        layout.addWidget(card)
        layout.addStretch()
        return scroll

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
        panes = QSplitter(Qt.Orientation.Vertical)
        panes.setChildrenCollapsible(False)
        layout.addWidget(panes, 1)

        tree_box = QWidget()
        tree_layout = QVBoxLayout(tree_box)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.addWidget(QLabel("文件夹 · 学期 → 课程 → 分类"))
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.currentItemChanged.connect(self.on_tree_selected)
        tree_layout.addWidget(self.folder_tree)
        panes.addWidget(tree_box)

        files_box = QWidget()
        files_layout = QVBoxLayout(files_box)
        files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_title = QLabel("文件 · 0 个")
        files_layout.addWidget(self.files_title)
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

    def root_path(self) -> Path | None:
        raw = self.root_edit.text().strip()
        path = Path(raw) if raw else None
        return path if path is not None and path.is_dir() else None

    def choose_root(self):
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
            return
        root = root.resolve()
        if self.root_edit.text() != str(root):
            self.root_edit.setText(str(root))
        if save:
            try:
                save_root(root)
            except OSError as exc:
                self.root_status.setText("目录可用，但设置保存失败：" + str(exc))
        self.root_status.setText("资料直接保存在此文件夹及其子目录中。")
        self.refresh_targets()
        self.refresh_browser(preferred=preferred or str(root), remember=save)

    def open_root(self):
        root = self.root_path()
        if root is None:
            self.root_status.setText("无法打开：资料总目录不存在，请重新选择。")
            return
        os.startfile(root)

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

    def _load_tree(self, root: Path):
        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()
        self.tree_items.clear()

        def append_folders(parent_item: QTreeWidgetItem | None, parent_path: Path, depth: int):
            if depth > 2:
                return
            try:
                children = sorted((p for p in parent_path.iterdir() if p.is_dir()), key=lambda p: p.name.casefold())
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

    def show_files(self, directory: Path, *, remember: bool = True):
        root = self.root_path()
        if root is None:
            return
        try:
            if not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
                raise ValueError("所选目录已失效或不在资料总目录内")
            files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
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
            os.startfile(self.current_directory)
        else:
            self.browser_path_label.setText("没有可打开的目录，请先选择资料总目录。")

    def open_selected_file(self, index):
        item = self.files_table.item(index.row(), 0)
        if item:
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            if path.is_file():
                os.startfile(path)

    def choose_image(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择课表图片", "", "图片 (*.png *.jpg *.jpeg)")
        if selected:
            self.set_image(Path(selected))

    def set_image(self, path: Path):
        self.image_path = path
        self.image_label.setText(str(path))
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.thumbnail.setText("图片无法预览，请检查文件格式")
            self.ocr_status.setText("图片读取失败")
            self.ocr_button.setEnabled(False)
        else:
            self.thumbnail.setPixmap(pixmap.scaled(560, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation))
            self.ocr_status.setText("图片已选择，点击“开始本地识别”。")
            self.ocr_button.setEnabled(True)

    def start_ocr(self):
        if not self.image_path or not self.image_path.is_file():
            self.ocr_status.setText("请先选择存在的课表图片。")
            return
        self.ocr_button.setEnabled(False)
        self.ocr_progress.setRange(0, 0)
        self.ocr_progress.setVisible(True)
        self.ocr_status.setText("正在本机识别课表，请稍候…")
        self.worker = OcrWorker(self.image_path)
        self.worker.completed.connect(self.ocr_finished)
        self.worker.failed.connect(self.ocr_failed)
        self.worker.finished.connect(self.ocr_stopped)
        self.worker.start()

    def ocr_stopped(self):
        self.ocr_button.setEnabled(True)
        self.ocr_progress.setVisible(False)

    def ocr_finished(self, lines: list[str]):
        candidates = extract_candidates(lines)
        self.courses_list.clear()
        for name in candidates:
            self._add_course_item(name)
        self.refresh_course_hint()
        if candidates:
            self.ocr_status.setText(f"识别完成：得到 {len(candidates)} 门候选课程。请核对名称后生成目录。")
        else:
            self.ocr_status.setText("识别完成，但未找到课程名称。可手动添加，或换一张清晰课表。")

    def ocr_failed(self, error: str):
        self.ocr_status.setText("本地 OCR 失败：" + error + "。仍可手动添加课程。")

    def _add_course_item(self, name: str):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.courses_list.addItem(item)

    def refresh_course_hint(self, *_):
        count = len([name for name in self.course_names() if name.strip()])
        self.course_hint.setText(f"当前 {count} 门课程。双击名称可编辑，也可手动添加或删除。" if count else
                                 "当前没有课程。识别课表或手动添加后即可生成目录。")

    def add_course(self):
        name = self.new_course.text().strip()
        if name:
            self._add_course_item(name)
            self.new_course.clear()
            self.refresh_course_hint()

    def edit_course(self):
        item = self.courses_list.currentItem()
        if item:
            self.courses_list.editItem(item)

    def delete_course(self):
        row = self.courses_list.currentRow()
        if row >= 0:
            self.courses_list.takeItem(row)
            self.refresh_course_hint()

    def course_names(self) -> list[str]:
        return [self.courses_list.item(i).text() for i in range(self.courses_list.count())]

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
            paths = preview_paths(root, self.semester_edit.text(), self.course_names())
            self.preview.addItems([f"{'已存在' if path.is_dir() else '待创建'}  ·  {path}" for path in paths])
            self.generate_status.setText(f"预览 {len(paths)} 个目录。已有目录会复用，不会覆盖其中的文件。")
            return True
        except ValueError as exc:
            self.generate_status.setText("无法预览：" + str(exc))
            return False

    def generate(self):
        if not self.show_preview():
            return
        try:
            root = self.root_path()
            semester_path, _ = self.plan()
            created, existing, failures = create_directories(root, self.semester_edit.text(), self.course_names())
            message = f"创建 {created}，已存在 {existing}，失败 {len(failures)}"
            if failures:
                message += "\n" + "\n".join(failures)
            self.generate_status.setText(message)
            self.refresh_targets(preferred=semester_path.name)
            self.refresh_browser(preferred=str(semester_path))
        except (OSError, ValueError) as exc:
            self.generate_status.setText("生成失败：" + str(exc))

    def refresh_targets(self, *_args, preferred: str | None = None):
        root = self.root_path()
        selected = preferred or self.archive_semester_combo.currentText()
        try:
            semesters = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()) if root else []
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
            courses = sorted((p for p in semester_path.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()) if semester_path and semester_path.is_dir() else []
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
        self.update_destination()

    def target_directory(self) -> Path | None:
        root = self.root_path()
        course_data = self.course_combo.currentData()
        category = self.category_combo.currentText()
        if root and course_data and category:
            course_path = Path(course_data)
            if course_path.is_dir() and course_path.resolve().is_relative_to(root.resolve()):
                return course_path / category
        return None

    def update_destination(self, *_):
        source_text = self.source_edit.text().strip()
        self.source_label.setText("来源文件：" + source_text if source_text else "来源文件：尚未选择")
        destination_dir = self.target_directory()
        if destination_dir is None:
            self.destination_label.setText("最终目标文件：请先选择资料目录并生成课程分类")
        elif not source_text:
            self.destination_label.setText("目标文件夹：" + str(destination_dir) + "\n请选择来源文件以预览最终文件名。")
        else:
            proposed = planned_copy_path(Path(source_text), destination_dir)
            suffix = "" if destination_dir.is_dir() else "\n目标分类尚未创建，请先生成目录。"
            self.destination_label.setText("最终目标文件：" + str(proposed) + suffix)

    def choose_file(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择待复制的文件")
        if selected:
            self.source_edit.setText(selected)

    def archive_file(self):
        destination = self.target_directory()
        try:
            if not self.source_edit.text().strip():
                raise ValueError("请先选择来源文件")
            if destination is None:
                raise ValueError("请先选择资料目录、学期、课程和分类")
            copied = copy_unique(Path(self.source_edit.text()), destination)
            self.last_target = destination
            self.archive_status.setText("复制成功，来源文件保持不变：" + str(copied))
            self.refresh_browser(preferred=str(destination))
            self.update_destination()
        except (OSError, ValueError) as exc:
            self.archive_status.setText("复制失败：" + str(exc))

    def open_destination(self):
        path = self.target_directory() or self.last_target
        if path and path.is_dir():
            os.startfile(path)
        else:
            self.archive_status.setText("目标分类文件夹不存在，请先生成目录。")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.ocr_status.setText("识别正在完成，请稍后关闭窗口。")
            event.ignore()
        else:
            super().closeEvent(event)


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #203247; }
QMainWindow, QScrollArea { background: #f3f6fa; }
QWidget#tabBody { background: #f3f6fa; }
QLabel#heading { font-size: 23px; font-weight: 700; color: #14283d; }
QLabel#subtitle, QLabel#muted { color: #64758a; }
QLabel#sectionTitle { font-size: 15px; font-weight: 700; }
QLabel#pathText { color: #35516e; }
QLabel#imagePreview { background: #f7f9fc; border: 1px dashed #b7c7d9; border-radius: 7px; color: #7a8897; }
QLabel#destination { padding: 12px; background: #eaf3ff; border: 1px solid #a9cef7; border-radius: 7px; color: #123d67; }
QFrame#rootCard, QGroupBox { background: white; border: 1px solid #d9e3ee; border-radius: 9px; }
QGroupBox { margin-top: 14px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 15px; padding: 0 5px; }
QLineEdit, QComboBox, QListWidget, QTreeWidget, QTableWidget { background: white; color: #203247; border: 1px solid #cbd8e5; border-radius: 5px; padding: 5px; }
QComboBox QAbstractItemView { background: white; color: #203247; selection-background-color: #dcecff; selection-color: #123d67; }
QComboBox:disabled { background: #f0f3f7; color: #617185; }
QLineEdit#rootPath { font-size: 14px; font-weight: 600; color: #123d67; background: #f8fbff; }
QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus { border: 1px solid #3380d7; }
QPushButton { background-color: #f7f9fc; color: #203247; border: 1px solid #c4d3e2; border-radius: 6px; padding: 8px 13px; font-weight: 600; }
QPushButton:hover { background-color: #eaf2fc; }
QPushButton#primary { background-color: #e5f0ff; color: #123d67; border-color: #1767bf; }
QPushButton#primary:hover { background-color: #d5e8ff; color: #0d3055; border-color: #0d54a5; }
QPushButton:disabled { background-color: #c7d1dc; color: #536579; }
QPushButton#primary:disabled { background-color: #d9e3ef; color: #52657a; border-color: #bdcede; }
QTabWidget::pane { border: 1px solid #d9e3ee; border-radius: 8px; background: #f3f6fa; }
QTabBar::tab { background: #e5ecf4; padding: 11px 14px; margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: white; color: #1767bf; font-weight: 700; }
QHeaderView::section { background: #edf3f9; padding: 6px; border: 0; border-bottom: 1px solid #d9e3ee; }
QSplitter::handle { background: #dce5ef; }
"""


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-ocr":
        output = Path(sys.argv[3])
        try:
            lines = local_ocr(Path(sys.argv[2]))
            output.write_text(json.dumps({"courses": extract_candidates(lines)}, ensure_ascii=False), encoding="utf-8")
            return 0
        except Exception as exc:
            output.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            return 1
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
