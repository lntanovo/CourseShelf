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
from tasks import BatchWorker, FileWorker, TaskWorker


class OcrWorker(TaskWorker):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, image: Path):
        super().__init__()
        self.image = image
        self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True

    def run(self):
        try:
            # An isolated process makes an in-flight ONNX call safely cancellable.
            with tempfile.TemporaryDirectory(prefix="courseshelf-ocr-") as temporary:
                output = Path(temporary) / "result.json"
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command.append(str(Path(__file__).resolve()))
                command.extend(["--verify-ocr", str(self.image), str(output)])
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    while process.poll() is None:
                        if self.cancel_requested:
                            raise Cancelled("识别已取消，原课程列表保留")
                        threading.Event().wait(0.04)
                    if self.cancel_requested:
                        raise Cancelled("识别已取消，原课程列表保留")
                    result = json.loads(output.read_text(encoding="utf-8"))
                    if process.returncode or "error" in result:
                        raise RuntimeError(result.get("error", "OCR 子进程失败"))
                    self.completed.emit(result["lines"])
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("ocr_failed image=%s", self.image)
            self.failed.emit(str(exc))


class DropFileEdit(QLineEdit):
    file_dropped = Signal(list)
    rejected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            self.file_dropped.emit([url.toLocalFile() for url in urls])
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self.rejected.emit("请拖入本地普通文件或文件夹")
            event.ignore()


class ImageDropZone(QLabel):
    image_dropped = Signal(str)
    rejected = Signal(str)
    clicked = Signal()

    def __init__(self):
        super().__init__("拖入一张 PNG / JPG 课表图片，或点击此处选择")
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(154)
        self.setObjectName("imagePreview")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.setProperty("dragging", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragging", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.dragLeaveEvent(event)
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            self.rejected.emit("请只拖入一张本地 PNG / JPG 图片")
            return
        self.image_dropped.emit(urls[0].toLocalFile())
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class FileDropTree(QTreeWidget):
    file_on_item = Signal(list, str)
    rejected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        item = self.itemAt(event.position().toPoint())
        if urls and all(url.isLocalFile() for url in urls) and item is not None:
            self.file_on_item.emit([url.toLocalFile() for url in urls], item.data(0, Qt.ItemDataRole.UserRole))
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            self.rejected.emit("请将本地文件或文件夹拖到课程或分类目录")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("学习资料整理")
        self.resize(1380, 860)
        self.setMinimumSize(1040, 680)
        self.image_path: Path | None = None
        self.worker: OcrWorker | None = None
        self.file_worker: FileWorker | None = None
        self._suggesting = False
        self.inbox_items = []
        self._loading_inbox = False
        self._selected_inbox = -1
        self.last_target: Path | None = None
        self.current_directory: Path | None = None
        self.tree_items: dict[Path, QTreeWidgetItem] = {}

        central = QWidget()
        self.setCentralWidget(central)
        toolbar = self.addToolBar("常用操作")
        toolbar.setMovable(False)
        for label, callback in (("选择资料目录", self.choose_root), ("导入课表", self.choose_image),
                                ("刷新磁盘", self.refresh_browser), ("打开资料目录", self.open_root),
                                ("帮助 / 关于", self.show_about)):
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(14)

        heading = QLabel("学习资料整理")
        heading.setObjectName("heading")
        outer.addWidget(heading)
        description = QLabel("识别课表 → 核对课程 → 生成目录 → 整理资料。所有资料都保存在你选择的本机文件夹中。")
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
        self.statusBar().showMessage("请选择资料总目录，或导入课表开始")

        settings = load_settings()
        remembered = settings.get("root")
        if isinstance(remembered, str) and remembered:
            if Path(remembered).is_dir():
                self.root_edit.setText(remembered)
                self.root_changed(save=False, preferred=settings.get("last_viewed"))
            else:
                self.root_edit.setText(remembered)
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
        self.root_edit.textChanged.connect(self.invalidate_preview)
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
        self.thumbnail = ImageDropZone()
        self.thumbnail.clicked.connect(self.choose_image)
        self.thumbnail.image_dropped.connect(lambda raw: self.set_image(Path(raw)))
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
        self.thumbnail.rejected.connect(self.ocr_status.setText)
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
        self.courses_list.itemChanged.connect(self.invalidate_preview)
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
        layout.addWidget(manage)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：整理资料  →", self.advance_to_archive, True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def _make_archive_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        note = QLabel("拖入文件或文件夹到收件箱。逐行核对建议后执行；默认复制，同名保留两个。")
        note.setWordWrap(True)
        layout.addWidget(note)
        card, card_layout = self._card("收件箱")
        row = QHBoxLayout()
        self.source_edit = DropFileEdit()
        self.source_edit.setPlaceholderText("拖入多个本地文件或文件夹；也可输入一个路径")
        self.source_edit.file_dropped.connect(self.add_to_inbox)
        self.source_edit.textChanged.connect(self.source_text_changed)
        row.addWidget(self.source_edit, 1)
        row.addWidget(self._button("添加文件", self.choose_file))
        row.addWidget(self._button("添加文件夹", self.choose_folder))
        card_layout.addLayout(row)
        self.recursive_check = QCheckBox("包含子文件夹（默认关闭）")
        card_layout.addWidget(self.recursive_check)
        self.inbox_table = QTableWidget(0, 7)
        self.inbox_table.setHorizontalHeaderLabels(["文件名", "大小", "课程", "分类", "理由", "操作", "状态"])
        self.inbox_table.setMinimumHeight(210)
        self.inbox_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inbox_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.inbox_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inbox_table.currentCellChanged.connect(self.select_inbox_row)
        self.inbox_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        card_layout.addWidget(self.inbox_table)
        actions = QHBoxLayout()
        actions.addWidget(self._button("应用全部高置信建议", self.apply_suggestions))
        actions.addWidget(self._button("清空收件箱", self.clear_inbox))
        actions.addWidget(self._button("仅重试失败项", self.retry_failed))
        card_layout.addLayout(actions)
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("同名：保留两个（默认）", "keep")
        self.conflict_combo.addItem("同名：跳过", "skip")
        card_layout.addWidget(self.conflict_combo)
        self.source_label = QLabel("来源：尚未选择文件")
        self.source_label.setObjectName("pathText")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_label.setWordWrap(True)
        self.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card_layout.addWidget(self.source_label)
        layout.addWidget(card)

        card, card_layout = self._card("选中行的目标位置")
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
        self.course_combo.currentIndexChanged.connect(self.refresh_categories)
        course_column.addWidget(self.course_combo)
        row.addLayout(course_column, 1)
        card_layout.addLayout(row)
        card_layout.addWidget(QLabel("分类"))
        self.category_combo = QComboBox()
        self.category_combo.currentIndexChanged.connect(self.update_destination)
        card_layout.addWidget(self.category_combo)
        self.suggestion_label = QLabel("文件名建议：选择来源文件后显示；最终以手动选择为准。")
        self.suggestion_label.setWordWrap(True)
        card_layout.addWidget(self.suggestion_label)
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
        self.copy_radio = QRadioButton("复制（默认，保留来源）")
        self.copy_radio.setChecked(True)
        self.move_radio = QRadioButton("移动（校验后删除来源）")
        row.addWidget(self.copy_radio)
        row.addWidget(self.move_radio)
        card_layout.addLayout(row)
        self.copy_radio.toggled.connect(self.batch_mode_changed)
        self.move_radio.toggled.connect(self.batch_mode_changed)
        row = QHBoxLayout()
        self.copy_button = self._button("确认复制到此位置", self.archive_file, True)
        row.addWidget(self.copy_button)
        self.cancel_file_button = self._button("取消操作", self.cancel_file)
        self.cancel_file_button.setEnabled(False)
        row.addWidget(self.cancel_file_button)
        row.addWidget(self._button("打开目标文件夹", self.open_destination))
        row.addStretch()
        card_layout.addLayout(row)
        self.file_progress = QProgressBar()
        self.file_progress.setVisible(False)
        card_layout.addWidget(self.file_progress)
        self.archive_status = QLabel("复制成功后，右侧文件列表会立即显示结果。")
        self.source_edit.rejected.connect(self.archive_status.setText)
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

    def choose_image(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择课表图片", "", "图片 (*.png *.jpg *.jpeg)")
        if selected:
            self.set_image(Path(selected))

    def set_image(self, path: Path):
        if not path.is_file() or path.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            self.ocr_status.setText("只接受一张存在的 PNG / JPG / JPEG 图片；原图片和课程保留。")
            return False
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.ocr_status.setText("图片无法解码；原图片和课程保留。")
            return False
        if self.image_path != path and self.courses_list.count() and QMessageBox.question(
                self, "替换课表图片", "已有课程列表。换图后原列表仍保留，开始重新识别时会清空。继续换图？", defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self.image_path = path
        self.image_label.setText(str(path))
        self.thumbnail.setPixmap(pixmap.scaled(560, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        self.ocr_status.setText("图片已选择，点击“开始本地识别”。")
        self.ocr_button.setEnabled(True)
        return True

    def start_ocr(self):
        if not self.image_path or not self.image_path.is_file():
            self.ocr_status.setText("请先选择存在的课表图片。")
            return
        if self.courses_list.count() and QMessageBox.question(
                self, "重新识别", "重新识别将替换已核对或手工修改的课程列表，继续？", defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
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
        self.invalidate_preview()

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
            self.invalidate_preview()

    def invalidate_preview(self, *_):
        if hasattr(self, "preview"):
            self.preview.clear()
            self.generate_status.setText("输入已变化，请重新预览当前目录计划。")

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
            added = build_inbox(paths, list(snapshot), snapshot, recursive=self.recursive_check.isChecked())
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
        for row, item in enumerate(self.inbox_items):
            self.inbox_table.setItem(row, 0, QTableWidgetItem(item.source.name))
            self.inbox_table.item(row, 0).setToolTip(str(item.source))
            self.inbox_table.setItem(row, 1, QTableWidgetItem(str(item.size)))
            course = QComboBox()
            course.addItem("需手选", None)
            for key in snapshot:
                course.addItem(key, key)
            course.setCurrentIndex(max(0, course.findData(item.course)))
            course.currentIndexChanged.connect(lambda _, r=row: self.row_course_changed(r))
            self.inbox_table.setCellWidget(row, 2, course)
            category = QComboBox()
            category.addItem("需手选", None)
            for name in snapshot.get(item.course, []):
                category.addItem(name, name)
            category.setCurrentIndex(max(0, category.findData(item.category)))
            category.currentIndexChanged.connect(lambda _, r=row: self.row_category_changed(r))
            self.inbox_table.setCellWidget(row, 3, category)
            self.inbox_table.setItem(row, 4, QTableWidgetItem(item.reason))
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
            result = suggest(source.name, courses)
            if result.course:
                self.course_combo.setCurrentText(result.course)
            else:
                self.course_combo.setCurrentIndex(-1)
            categories = [self.category_combo.itemText(i) for i in range(self.category_combo.count())]
            result = suggest(source.name, courses, categories)
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

    def open_destination(self):
        path = self.target_directory() or self.last_target
        if path and path.is_dir():
            open_with_shell(path, self.statusBar().showMessage)
        else:
            self.archive_status.setText("目标分类文件夹不存在，请先生成目录。")

    def closeEvent(self, event):
        workers = [worker for worker in (self.worker, self.file_worker)
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
            output.write_text(json.dumps({"courses": extract_candidates(lines), "lines": lines}, ensure_ascii=False), encoding="utf-8")
            return 0
        except Exception as exc:
            output.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            return 1
    if len(sys.argv) == 5 and sys.argv[1] == "--verify-archive":
        root, source, output = map(Path, sys.argv[2:5])
        try:
            _, _, failures, _ = create_plan(root, "打包验收", ["示例课程"])
            if failures:
                raise OSError("; ".join(failures))
            target = transfer(source, root / "打包验收" / "示例课程" / "课件", root=root, mode="copy")
            output.write_text(json.dumps({"target": str(target)}, ensure_ascii=False), encoding="utf-8")
            return 0
        except Exception as exc:
            output.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            return 1
    app = QApplication(sys.argv)
    configure_logging()
    install_exception_hooks()
    instance_lock = acquire_instance()
    if instance_lock is None:
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
