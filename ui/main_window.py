"""A quiet desktop shell with one workspace visible at a time."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QStyle, QTabWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from organizer import load_settings
from tasks import FileWorker, OcrWorker
from .appearance import AppearanceMixin, BackgroundCanvas
from .root import RootMixin
from .tabs.ocr import OcrMixin
from .tabs.generate import GenerateMixin
from .tabs.archive import ArchiveMixin
from .tabs.browser import BrowserMixin
from .tabs.history import HistoryMixin
from .widgets import StatusLabel

PAGES = {
    0: "课表与课程",
    1: "生成目录",
    2: "整理资料",
    3: "操作记录",
    4: "资料库",
}


class MainWindow(AppearanceMixin, RootMixin, OcrMixin, GenerateMixin, ArchiveMixin, BrowserMixin, HistoryMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        from runtime import initialize_gui
        initialize_gui()
        self.setWindowTitle("CourseShelf")
        self.resize(1360, 880)
        self.setMinimumSize(1040, 720)
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

        self.canvas = BackgroundCanvas()
        self.setCentralWidget(self.canvas)
        shell = QHBoxLayout(self.canvas)
        shell.setContentsMargins(20, 20, 24, 14)
        shell.setSpacing(28)
        shell.addWidget(self._make_sidebar())
        workspace = QVBoxLayout()
        workspace.setSpacing(16)
        shell.addLayout(workspace, 1)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_heading = QLabel()
        self.page_heading.setObjectName("heading")
        titles.addWidget(self.page_heading)
        top.addLayout(titles, 1)
        appearance = self._button("外观与背景", self.open_appearance)
        appearance.setObjectName("quiet")
        top.addWidget(appearance, alignment=Qt.AlignmentFlag.AlignTop)
        workspace.addLayout(top)
        workspace.addWidget(self._make_root_card())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_ocr_tab(), "课表与课程")
        self.tabs.addTab(self._make_generate_tab(), "生成目录")
        self.tabs.addTab(self._make_archive_tab(), "整理资料")
        self.tabs.addTab(self._make_history_tab(), "操作记录")
        self.tabs.addTab(self._make_browser(), "资料库")
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self._page_changed)
        workspace.addWidget(self.tabs, 1)
        self._page_changed(0)
        self.statusBar().hide()
        self.statusBar().messageChanged.connect(lambda message: self.statusBar().setVisible(bool(message)))
        self.initialize_appearance()

        settings = load_settings()
        remembered = settings.get("root")
        if isinstance(remembered, str) and remembered:
            self.root_edit.setText(remembered)
            if Path(remembered).is_dir():
                self.root_changed(save=False, preferred=settings.get("last_viewed"))
                self.tabs.setCurrentIndex(2)
            else:
                self.root_status.setText("上次的资料目录已失效，请重新选择文件夹。")
                QTimer.singleShot(0, lambda: QMessageBox.warning(
                    self, "资料目录不可用", "上次使用的资料目录已不存在，请重新选择现有文件夹。\n" + remembered))
        else:
            self.root_status.setText("选择资料库后，即可开始整理。")
        self.refresh_targets()

    def _make_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(194)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 26, 16, 18)
        layout.setSpacing(8)
        brand = QLabel("CourseShelf")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(30)
        self.navigation = QButtonGroup(self)
        self.nav_buttons = {}
        for index, icon in ((2, QStyle.StandardPixmap.SP_FileDialogDetailedView),
                            (4, QStyle.StandardPixmap.SP_DirIcon),
                            (0, QStyle.StandardPixmap.SP_FileDialogContentsView),
                            (1, QStyle.StandardPixmap.SP_FileDialogNewFolder),
                            (3, QStyle.StandardPixmap.SP_FileDialogInfoView)):
            if index == 0:
                layout.addSpacing(20)
                label = QLabel("新学期")
                label.setObjectName("eyebrow")
                layout.addWidget(label)
            if index == 3:
                layout.addSpacing(20)
            button = QPushButton(PAGES[index])
            button.setObjectName("nav")
            button.setIcon(self.style().standardIcon(icon))
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            self.navigation.addButton(button, index)
            self.nav_buttons[index] = button
            layout.addWidget(button)
        layout.addStretch()
        about = self._button("关于 CourseShelf", self.show_about)
        about.setObjectName("quiet")
        layout.addWidget(about)
        return sidebar

    def _page_changed(self, index):
        self.page_heading.setText(PAGES[index])
        self.nav_buttons[index].setChecked(True)

    @staticmethod
    def _button(text: str, callback, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
        card = QGroupBox(title)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 24, 20, 18)
        layout.setSpacing(12)
        return card, layout

    @staticmethod
    def _scroll_content() -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("tabBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(16)
        scroll.setWidget(body)
        return scroll, layout

    def _make_root_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("rootCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(2)
        row = QHBoxLayout()
        label = QLabel("资料库")
        label.setObjectName("sectionTitle")
        row.addWidget(label)
        self.root_edit = QLineEdit()
        self.root_edit.setObjectName("rootPath")
        self.root_edit.setPlaceholderText("选择已有文件夹，或粘贴本机路径并按 Enter")
        self.root_edit.editingFinished.connect(self.root_changed)
        self.root_edit.textChanged.connect(self.invalidate_preview)
        row.addWidget(self.root_edit, 1)
        row.addWidget(self._button("更换", self.choose_root))
        row.addWidget(self._button("打开文件夹", self.open_root))
        layout.addLayout(row)
        self.root_status = StatusLabel()
        self.root_status.setObjectName("muted")
        self.root_status.setWordWrap(True)
        layout.addWidget(self.root_status)
        return card
