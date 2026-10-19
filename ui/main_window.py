"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QTabWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import load_settings
from tasks import FileWorker


from tasks import OcrWorker
from .root import RootMixin
from .tabs.ocr import OcrMixin
from .tabs.generate import GenerateMixin
from .tabs.archive import ArchiveMixin
from .tabs.browser import BrowserMixin
from .tabs.history import HistoryMixin
from .style import STYLE

class MainWindow(RootMixin, OcrMixin, GenerateMixin, ArchiveMixin, BrowserMixin, HistoryMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        from runtime import initialize_gui
        initialize_gui()
        self.setWindowTitle("CourseShelf")
        self.resize(1380, 860)
        self.setMinimumSize(1040, 680)
        self.image_path: Path | None = None
        self.worker: OcrWorker | None = None
        self.file_worker: FileWorker | None = None
        self._suggesting = False
        self.inbox_items = []
        self._loading_inbox = False
        self._selected_inbox = -1
        self.scan_worker = None
        self.undo_worker = None
        self._scan_pending = False
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

        heading = QLabel("CourseShelf")
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
        self.tabs.addTab(self._make_history_tab(), "4  操作记录")
        horizontal.addWidget(self.tabs)
        horizontal.addWidget(self._make_browser())
        horizontal.setSizes([760, 580])
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

