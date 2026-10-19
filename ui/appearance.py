"""Local theme and wallpaper controls; image paths are never uploaded or copied."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QColor, QImageReader, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from services.preferences import load_preferences, normalize, save_preferences
from .style import THEMES, stylesheet


def read_background(path):
    from services.browser import local_path
    path = Path(path)
    if not local_path(path) or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
        raise ValueError("请选择本机的 PNG、JPG 或 BMP 图片")
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("图片超过 30 MiB，请选择较小的图片")
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 100_000_000:
        raise ValueError("图片尺寸过大或无法解码")
    if max(size.width(), size.height()) > 2048:
        reader.setScaledSize(size.scaled(QSize(2048, 2048), Qt.AspectRatioMode.KeepAspectRatio))
    result = reader.read()
    if result.isNull():
        raise ValueError("图片无法读取，请尝试另一张图片")
    return QPixmap.fromImage(result)


class BackgroundCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.base = QColor(THEMES["paper"]["base"])
        self.picture = QPixmap()
        self.background_path = ""
        self.visibility = 35
        self._scaled = QPixmap()
        self._scaled_size = QSize()

    def apply(self, preferences):
        self.base = QColor(THEMES[preferences["theme"]]["base"])
        self.visibility = preferences["visibility"]
        path = preferences["background"]
        error = ""
        if path != self.background_path:
            self.picture = QPixmap()
            self.background_path = path
            if path:
                try:
                    self.picture = read_background(path)
                except (OSError, ValueError) as exc:
                    error = "背景图不可用，已使用主题底色：" + str(exc)
            self._scaled_size = QSize()
        self.update()
        return error

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.base)
        if not self.picture.isNull() and self.visibility:
            if self._scaled_size != self.size():
                self._scaled = self.picture.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                   Qt.TransformationMode.SmoothTransformation)
                self._scaled_size = self.size()
            painter.setOpacity(self.visibility / 100)
            painter.drawPixmap((self.width() - self._scaled.width()) // 2,
                               (self.height() - self._scaled.height()) // 2, self._scaled)


class AppearanceDialog(QDialog):
    changed = Signal(object)

    def __init__(self, parent, preferences):
        super().__init__(parent)
        self.preferences = dict(preferences)
        self.setWindowTitle("外观与背景")
        self.setMinimumWidth(540)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        title = QLabel("让资料库，像你喜欢的样子")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        description = QLabel("选择主题即时预览，关闭后自动记住。")
        description.setObjectName("muted")
        layout.addWidget(description)
        grid = QGridLayout()
        self.theme_group = QButtonGroup(self)
        self.theme_buttons = {}
        for i, (key, palette) in enumerate(THEMES.items()):
            button = QPushButton(palette["name"] + "\n" + palette["hint"])
            button.setObjectName("themeChoice")
            button.setCheckable(True)
            button.setChecked(key == preferences["theme"])
            button.clicked.connect(lambda checked=False, k=key: self.choose_theme(k))
            self.theme_group.addButton(button)
            self.theme_buttons[key] = button
            grid.addWidget(button, i // 2, i % 2)
        layout.addLayout(grid)
        self.background_label = QLabel()
        self.background_label.setObjectName("muted")
        self.background_label.setWordWrap(True)
        layout.addWidget(self.background_label)
        row = QHBoxLayout()
        choose = QPushButton("选择背景图片…")
        choose.clicked.connect(self.choose_background)
        row.addWidget(choose)
        self.remove_button = QPushButton("移除背景")
        self.remove_button.clicked.connect(lambda: self.set_background(""))
        row.addWidget(self.remove_button)
        row.addStretch()
        layout.addLayout(row)
        self.visibility_label = QLabel()
        layout.addWidget(self.visibility_label)
        self.visibility = QSlider(Qt.Orientation.Horizontal)
        self.visibility.setRange(0, 80)
        self.visibility.setValue(preferences["visibility"])
        self.visibility.valueChanged.connect(self.change_visibility)
        layout.addWidget(self.visibility)
        self.error = QLabel("")
        self.error.setObjectName("warning")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        row = QHBoxLayout()
        restore = QPushButton("恢复默认外观")
        restore.clicked.connect(self.restore_defaults)
        row.addWidget(restore)
        row.addStretch()
        done = QPushButton("完成")
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        row.addWidget(done)
        layout.addLayout(row)
        self.update_labels()

    def update_labels(self):
        path = self.preferences["background"]
        self.background_label.setText("背景 · " + (Path(path).name if path else "未设置，使用主题底色"))
        self.background_label.setToolTip(path)
        self.remove_button.setEnabled(bool(path))
        self.visibility_label.setText(f"背景可见度 · {self.preferences['visibility']}%")

    def choose_theme(self, theme):
        self.preferences["theme"] = theme
        self.changed.emit(dict(self.preferences))

    def choose_background(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择本机背景图片", "", "图片 (*.png *.jpg *.jpeg *.bmp)")
        if selected:
            self.set_background(selected)

    def set_background(self, path):
        try:
            if path:
                read_background(path)
            self.preferences["background"] = str(Path(path).resolve()) if path else ""
            self.error.clear()
            self.update_labels()
            self.changed.emit(dict(self.preferences))
            return True
        except (OSError, ValueError) as exc:
            self.error.setText(str(exc))
            return False

    def change_visibility(self, value):
        self.preferences["visibility"] = value
        self.update_labels()
        self.changed.emit(dict(self.preferences))

    def restore_defaults(self):
        self.preferences = normalize({})
        self.theme_buttons["paper"].setChecked(True)
        self.visibility.blockSignals(True)
        self.visibility.setValue(35)
        self.visibility.blockSignals(False)
        self.error.clear()
        self.update_labels()
        self.changed.emit(dict(self.preferences))


class AppearanceMixin:
    def initialize_appearance(self):
        self.appearance = load_preferences()
        self._appearance_dialog = None
        self.appearance_timer = QTimer(self)
        self.appearance_timer.setSingleShot(True)
        self.appearance_timer.setInterval(250)
        self.appearance_timer.timeout.connect(self.save_appearance)
        self.apply_appearance(self.appearance, persist=False)

    def apply_appearance(self, preferences, persist=True):
        self.appearance = normalize(preferences)
        p = THEMES[self.appearance["theme"]]
        palette = self.palette()
        for role, key in ((QPalette.ColorRole.Window, "base"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "field"), (QPalette.ColorRole.Text, "text"),
                          (QPalette.ColorRole.Button, "surface"), (QPalette.ColorRole.ButtonText, "text"),
                          (QPalette.ColorRole.Highlight, "selection"), (QPalette.ColorRole.HighlightedText, "text"),
                          (QPalette.ColorRole.PlaceholderText, "muted")):
            palette.setColor(role, QColor(p[key]))
        self.setPalette(palette)
        self.setStyleSheet(stylesheet(self.appearance["theme"]))
        error = self.canvas.apply(self.appearance)
        if error:
            self.statusBar().showMessage(error)
        if persist:
            self.appearance_timer.start()

    def save_appearance(self):
        self.appearance_timer.stop()
        try:
            save_preferences(self.appearance)
        except OSError as exc:
            self.statusBar().showMessage("外观已应用，但无法保存设置：" + str(exc))

    def open_appearance(self):
        if self._appearance_dialog is None:
            dialog = AppearanceDialog(self, self.appearance)
            self._appearance_dialog = dialog
            dialog.changed.connect(self.apply_appearance)
            dialog.finished.connect(lambda: self.save_appearance())
            dialog.destroyed.connect(lambda: setattr(self, "_appearance_dialog", None))
        self._appearance_dialog.show()
        self._appearance_dialog.raise_()
        self._appearance_dialog.activateWindow()
