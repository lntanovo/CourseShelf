from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QLabel, QTreeWidget

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

