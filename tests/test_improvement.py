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
        configure_logging()

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

        with patch("runtime._bridge", bridge), patch("tasks.transfer", side_effect=RuntimeError("injected archive failure")), patch.object(QMessageBox, "exec", inspect_box):
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

    def prepare_batch(self):
        from inbox import build_inbox
        create_plan(self.root, "秋季", ["数学"])
        paths = []
        for index in range(20):
            folder = self.base / f"source{index}"
            folder.mkdir()
            name = "未知.pdf" if index >= 18 else f"数学-课件-{index if index >= 9 else index // 3}.pdf"
            source = folder / name
            source.write_text(str(index))
            paths.append(source)
        items = build_inbox(paths, ["秋季/数学"], {"秋季/数学": ["课件", "其他"]})
        for item in items:
            item.course, item.category = item.suggested_course, item.suggested_category
        return items

    def run_batch(self, items, **kwargs):
        from tasks import BatchWorker
        results, summaries = [], []
        worker = BatchWorker(items, self.root, **kwargs)
        worker.item_done.connect(lambda i, result: results.append((i, result)))
        worker.completed.connect(summaries.append)
        worker.start()
        wait_worker(worker)
        return results, summaries[0]

    def test_batch_twenty_and_unmatched(self):
        items = self.prepare_batch()
        results, summary = self.run_batch(items)
        self.assertEqual(summary, {"ok": 18, "skipped": 2, "failed": 0})
        self.assertIn("(2)", results[2][1]["target"])
        for index, result in results:
            self.assertTrue(items[index].source.exists())
            if result["status"] == "ok":
                self.assertEqual(Path(result["target"]).read_bytes(), items[index].source.read_bytes())
        self.assertEqual(len(list(self.root.rglob("*.pdf"))), 18)

    def test_batch_cancel_and_all_fail_retry(self):
        from tasks import BatchWorker
        from file_ops import transfer
        items = self.prepare_batch()
        worker = BatchWorker(items, self.root)
        results = []
        worker.item_done.connect(lambda i, r: results.append(r))

        def cancel_after_first(*args, **kwargs):
            target = transfer(*args, **kwargs)
            worker.request_cancel()
            return target

        with patch("tasks.transfer", side_effect=cancel_after_first):
            worker.start()
            wait_worker(worker)
        self.assertEqual([r["status"] for r in results], ["ok"] + ["skipped"] * 19)
        self.assertFalse(list(self.root.rglob(".courseshelf-partial-*")))
        for item in items:
            self.assertTrue(item.source.exists())
            item.course, item.category = "秋季/数学", "课件"
        with patch("tasks.transfer", side_effect=PermissionError("read-only target")):
            _, summary = self.run_batch(items)
        self.assertEqual(summary["failed"], 20)
        _, summary = self.run_batch(items)
        self.assertEqual(summary["ok"], 20)

    def test_inbox_folder_expansion_and_ui(self):
        from inbox import build_inbox
        items = self.prepare_batch()
        folder = self.base / "incoming"
        folder.mkdir()
        (folder / "数学课件.txt").write_text("a")
        (folder / "sub").mkdir()
        (folder / "sub/数学作业.txt").write_text("b")
        snapshot = {"秋季/数学": ["课件", "作业"]}
        self.assertEqual(len(build_inbox([folder], list(snapshot), snapshot)), 1)
        self.assertEqual(len(build_inbox([folder], list(snapshot), snapshot, recursive=True)), 2)
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        window.add_to_inbox([item.source for item in items])
        self.assertEqual(window.inbox_table.rowCount(), 20)
        self.assertTrue(all(item.course is None for item in window.inbox_items))
        window.apply_suggestions()
        window.archive_file()
        wait_worker(window.file_worker)
        self.assertIn("跳过 2", window.archive_status.text())
        self.assertEqual(sum(item.status == "ok" for item in window.inbox_items), 18)
        window.close()


if __name__ == "__main__":
    unittest.main()
