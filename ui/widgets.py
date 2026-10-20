from PySide6.QtCore import Qt, Signal, QPointF, QSize
from PySide6.QtGui import QPainter, QPen, QPalette, QPolygonF
from PySide6.QtWidgets import QLineEdit, QLabel, QTreeWidget, QToolButton, QVBoxLayout, QWidget, QTableWidget, QComboBox, QStyledItemDelegate


class StatusLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setVisible(bool(text))

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText("")


class CourseDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(size.height(), option.fontMetrics.height() + 18))

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setObjectName("courseEditor")
            editor.setStyleSheet("QLineEdit#courseEditor { padding: 0px 6px; min-height: 0px; border-radius: 5px; }")
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(0, 1, 0, -1))


class DirectoryPreview(QTreeWidget):
    def path_count(self):
        def total(item):
            return 1 + sum(total(item.child(i)) for i in range(item.childCount()))
        return sum(total(self.topLevelItem(i)) for i in range(self.topLevelItemCount()))


class SoftComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Text), 1.2))
        x, y = self.width() - 13, self.height() / 2
        painter.drawPolyline(QPolygonF([QPointF(x - 3, y - 1), QPointF(x, y + 2), QPointF(x + 3, y - 1)]))


class Disclosure(QWidget):
    """Keep secondary controls available without filling the initial screen."""
    def __init__(self, title, content, expanded=False):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName("disclosure")
        self.toggle.setText(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.content = content
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)


class InboxTable(QTableWidget):
    file_dropped = Signal(list)

    def __init__(self):
        super().__init__(0, 7)
        self.setAcceptDrops(True)
        self._compact = None
        self.empty = QLabel("暂无文件", self.viewport())
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def setRowCount(self, count):
        super().setRowCount(count)
        self.empty.setVisible(count == 0)
        self.empty.setGeometry(self.viewport().rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty.setGeometry(self.viewport().rect())
        compact = self.viewport().width() < 850
        if self._compact != compact:
            self._compact = compact
            self.setColumnHidden(1, compact)
            for column, width in ((2, 165 if compact else 210), (3, 90 if compact else 105),
                                  (5, 80), (6, 135 if compact else 170)):
                self.setColumnWidth(column, width)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            self.file_dropped.emit([url.toLocalFile() for url in urls])
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

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

