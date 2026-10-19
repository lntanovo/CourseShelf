"""Regression and acceptance tests; all data operations use temporary roots."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import FileWorker, MainWindow
from catalog import (CatalogError, create_plan, import_course, load_catalog, missing_paths,
                     restore_defaults, save_catalog)
from dialogs import confirmation
from runtime import ErrorBridge, acquire_instance, configure_logging, log, open_with_shell

APP = QApplication.instance() or QApplication([])


def wait_worker(worker, timeout=30000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    worker.finished.connect(loop.quit)
    timer.start(timeout)
    if worker.isRunning():
        loop.exec()
    APP.processEvents()
    assert not worker.isRunning(), "worker timeout"


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="courseshelf-improve-")
        self.base = Path(self.temp.name)
        self.root = self.base / "library"
        self.root.mkdir()
        self.environment = patch.dict(os.environ, {"FILES_ORGANIZER_CONFIG_DIR": str(self.base / "settings")})
        self.environment.start()

    def tearDown(self):
        for handler in list(log.handlers):
            log.removeHandler(handler)
            handler.close()
        self.environment.stop()
        self.temp.cleanup()

    def test_partial_plan_and_default_restore(self):
        mkdir = Path.mkdir

        def blocked(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            if path.name == "数学":
                (path / "课件").write_text("block")
            return result

        with patch.object(Path, "mkdir", blocked):
            _, _, failures, _ = create_plan(self.root, "秋季", ["数学"])
        self.assertEqual(len(failures), 1)
        data = load_catalog(self.root)
        self.assertEqual(data["courses"]["秋季/数学"]["categories"], ["作业", "复习资料", "其他"])
        (self.root / "秋季/数学/作业").rmdir()
        self.assertIn(self.root / "秋季/数学/作业", missing_paths(self.root))
        with self.assertRaises(CatalogError):
            restore_defaults(self.root, "秋季", "数学")
        self.assertTrue((self.root / "秋季/数学/作业").is_dir())
        self.assertIn("作业", load_catalog(self.root)["courses"]["秋季/数学"]["categories"])

    def test_resync_preserves_order_and_future_catalog(self):
        create_plan(self.root, "秋季", ["数学"])
        data = load_catalog(self.root)
        data["courses"]["秋季/数学"]["categories"].reverse()
        save_catalog(self.root, data)
        import_course(self.root, "秋季", "数学")
        self.assertEqual(load_catalog(self.root), data)
        path = self.root / ".courseshelf.json"
        path.write_text('{"schema_version":99,"courses":{}}')
        original = path.read_bytes()
        self.assertTrue(load_catalog(self.root)["_read_only"])
        with self.assertRaises(CatalogError):
            create_plan(self.root, "new", ["other"])
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        self.assertIn("更新版本", window.missing_label.text())
        window.close()
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "new").exists())

    def test_safe_dialog_shell_logging_and_lock(self):
        box = confirmation(None, "移至回收站", "test", "移至回收站")
        self.assertEqual(box.defaultButton(), box.button(QMessageBox.StandardButton.No))
        self.assertEqual(box.escapeButton(), box.button(QMessageBox.StandardButton.No))
        logfile = configure_logging()
        bridge = ErrorBridge()
        details = []

        def inspect_box(box):
            details.append(box.detailedText())
            for button in box.buttons():
                if button.text() == "复制错误详情":
                    button.click()

        with patch("runtime._bridge", bridge), patch("app.transfer", side_effect=RuntimeError("injected archive failure")), patch.object(QMessageBox, "exec", inspect_box):
            FileWorker(self.base / "source", self.root, self.root, "copy").run()
            APP.processEvents()
        self.assertIn("injected archive failure", details[0])
        self.assertEqual(APP.clipboard().text(), details[0])
        self.assertIn("Traceback", logfile.read_text(encoding="utf-8"))
        status = []
        with patch("os.startfile", side_effect=OSError("missing")):
            self.assertFalse(open_with_shell(self.base / "gone", status.append))
        self.assertIn("无法打开", status[0])
        lock = acquire_instance()
        self.assertIsNotNone(lock)
        with patch.object(QMessageBox, "information") as message:
            self.assertIsNone(acquire_instance())
        self.assertTrue(message.called)
        lock.unlock()

    def test_ocr_cancel(self):
        from smoke_demo import make_sample
        image = self.base / "sample.png"
        make_sample(image)
        window = MainWindow()
        window.set_image(image)
        window.show()
        window.start_ocr()
        with patch("app.confirm", return_value=True):
            window.close()
        wait_worker(window.worker)
        self.assertFalse(window.isVisible())


if __name__ == "__main__":
    unittest.main()
