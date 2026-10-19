"""Local diagnostics, safe shell access and single-instance lifecycle."""
from __future__ import annotations

import ctypes
import logging
import os
import platform
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, Qt, Signal
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from organizer import settings_path

VERSION = "1.1.0"
log = logging.getLogger("courseshelf")

_gui_initialized = False


def initialize_gui():
    global _gui_initialized
    if _gui_initialized:
        return
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    QApplication.instance().setWindowIcon(QIcon(str(Path(__file__).parent / "assets/courseshelf.ico")))
    _gui_initialized = True


class ErrorBridge(QObject):
    reported = Signal(str)

    def __init__(self):
        super().__init__()
        self.reported.connect(self.show_error, Qt.ConnectionType.QueuedConnection)

    def show_error(self, details):
        box = QMessageBox(QApplication.activeWindow())
        box.setWindowTitle("CourseShelf 遇到错误")
        box.setText("操作未完成。错误详情已写入本地日志。")
        box.setDetailedText(details)
        copy = box.addButton("复制错误详情", QMessageBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()


_bridge = None


def configure_logging():
    directory = settings_path().parent / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "app.log"
    for handler in list(log.handlers):
        log.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(destination, maxBytes=5 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.info("startup version=%s python=%s platform=%s data=%s", VERSION,
             sys.version, platform.platform(), settings_path().parent)
    return destination


def report_exception(kind, value, tb):
    details = "".join(traceback.format_exception(kind, value, tb))
    log.error("unhandled_exception\n%s", details)
    if _bridge is not None:
        _bridge.reported.emit(details)


def install_exception_hooks():
    global _bridge
    _bridge = ErrorBridge()
    sys.excepthook = report_exception
    threading.excepthook = lambda args: report_exception(args.exc_type, args.exc_value, args.exc_traceback)


def open_with_shell(path: Path, status):
    try:
        os.startfile(path)
        return True
    except OSError as exc:
        log.exception("shell_open path=%s", path)
        status("无法打开：" + str(path) + "；" + str(exc))
        return False


def acquire_instance():
    directory = settings_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "app.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(0):
        return lock
    if os.name == "nt":
        for title in ("CourseShelf",):
            window = ctypes.windll.user32.FindWindowW(None, title)
            if window:
                ctypes.windll.user32.ShowWindow(window, 9)
                ctypes.windll.user32.SetForegroundWindow(window)
                break
    QMessageBox.information(None, "CourseShelf 已在运行", "CourseShelf 已在运行，请使用已有窗口。")
    return None
