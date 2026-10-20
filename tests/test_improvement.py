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
        self.base = Path(self.temp.name).resolve()  # Windows runners may return an 8.3 TEMP path.
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
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTimer.singleShot(0, lambda: QTest.keyClick(box, Qt.Key.Key_Return))
        self.assertEqual(box.exec(), QMessageBox.StandardButton.No)
        logfile = configure_logging()
        bridge = ErrorBridge()
        details = []

        def inspect_box(box):
            details.append(box.detailedText())
            for button in box.buttons():
                if button.text() == "复制错误详情":
                    button.click()

        with patch("runtime._bridge", bridge), patch("tasks.worker.transfer", side_effect=RuntimeError("injected archive failure")), patch.object(QMessageBox, "exec", inspect_box):
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
        from tests.smoke_demo import make_sample
        image = self.base / "sample.png"
        make_sample(image)
        window = MainWindow()
        window.set_image(image)
        window.show()
        window.start_ocr()
        with patch("ui.root.confirm", return_value=True):
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

        with patch("tasks.worker.transfer", side_effect=cancel_after_first):
            worker.start()
            wait_worker(worker)
        self.assertEqual([r["status"] for r in results], ["ok"] + ["skipped"] * 19)
        self.assertFalse(list(self.root.rglob(".courseshelf-partial-*")))
        for index, item in enumerate(items):
            self.assertTrue(item.source.exists())
            item.course, item.category = "秋季/数学", "课件"
            item.source.write_text(f"retry-{index}")
        with patch("tasks.worker.transfer", side_effect=PermissionError("read-only target")):
            _, summary = self.run_batch(items)
        self.assertEqual(summary["failed"], 20)
        _, summary = self.run_batch(items)
        self.assertEqual(summary, {"ok": 20, "skipped": 0, "failed": 0})

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
        self.assertIn("2 项需选目标", window.archive_status.text())
        self.assertEqual(sum(item.status == "pending" for item in window.inbox_items), 2)
        self.assertEqual(sum(item.status == "ok" for item in window.inbox_items), 18)
        window.close()

    def test_index_rebuild_rename_and_corruption(self):
        from library_index import index_path, scan, search
        create_plan(self.root, "秋季", [f"课程{i}" for i in range(10)])
        for folder in self.root.glob("秋季/*/课件"):
            for number in range(50):
                (folder / f"讲义{number}.txt").write_text(str(number))
        self.assertEqual(scan(self.root), 500)
        self.assertEqual(len(search(self.root, "讲义", course="课程1")), 50)
        index_path().unlink()
        self.assertEqual(scan(self.root), 500)
        old = self.root / "秋季/课程1/课件/讲义1.txt"
        old.rename(old.with_name("renamed.txt"))
        scan(self.root)
        self.assertFalse(any(record["rel_path"].endswith("/讲义1.txt") for record in search(self.root, course="课程1")))
        self.assertEqual(len(search(self.root, "renamed")), 1)
        index_path().write_bytes(b"broken sqlite cache")
        self.assertEqual(scan(self.root), 500)
        self.assertEqual(len(search(self.root, "renamed")), 1)
        self.assertEqual(search(self.root, "%"), [])

    def test_index_ui_auto_rebuild(self):
        from library_index import index_path
        create_plan(self.root, "秋季", ["数学"])
        (self.root / "秋季/数学/课件/search-me.txt").write_text("cached")
        for _ in range(2):
            window = MainWindow()
            window.root_edit.setText(str(self.root))
            window.root_changed()
            wait_worker(window.scan_worker)
            window.search_edit.setText("search-me")
            window.search_files()
            self.assertEqual(window.files_table.rowCount(), 1)
            window.close()
            index_path().unlink()

    def test_history_undo_and_dedup(self):
        from history import operations, undo
        from library_index import index_path, scan
        items = self.prepare_batch()[:1]
        results, _ = self.run_batch(items)
        target = Path(results[0][1]["target"])
        operation = next(row for row in operations(self.root) if row["kind"] == "copy")
        scan(self.root)
        index_path().unlink()
        self.assertIn("撤销完成", undo(self.root, operation["id"]))
        self.assertFalse(target.exists())
        self.assertTrue(items[0].source.exists())
        with self.assertRaisesRegex(ValueError, "已撤销"):
            undo(self.root, operation["id"])
        results, _ = self.run_batch(items)
        target = Path(results[0][1]["target"])
        operation = next(row for row in operations(self.root) if row["kind"] == "copy")
        target.write_text("changed target")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            undo(self.root, operation["id"])
        self.assertEqual(target.read_text(), "changed target")
        _, summary = self.run_batch(items)
        self.assertEqual(summary["ok"], 1)  # same name, different content preserves both
        _, summary = self.run_batch(items)
        self.assertEqual(summary["ok"], 1)  # different target content still preserves both
        self.assertTrue(any(row["kind"] == "undo" and row["result"] == "failed" for row in operations(self.root)))

    def test_identical_skip_and_move_undo_original_name(self):
        from history import operations, undo
        items = self.prepare_batch()[:1]
        _, first = self.run_batch(items)
        _, duplicate = self.run_batch(items)
        self.assertEqual((first["ok"], duplicate["skipped"]), (1, 1))
        source = items[0].source
        source.write_text("new content")
        items[0].mode = "move"
        results, summary = self.run_batch(items)
        self.assertEqual(summary["ok"], 1)
        target = Path(results[0][1]["target"])
        self.assertIn("(1)", target.name)
        self.assertFalse(source.exists())
        operation = next(row for row in operations(self.root) if row["kind"] == "move")
        source.write_text("occupied")
        with self.assertRaisesRegex(ValueError, "占用"):
            undo(self.root, operation["id"])
        source.unlink()  # only a temporary test fixture
        undo(self.root, operation["id"])
        self.assertEqual(source.read_text(), "new content")
        self.assertFalse(target.exists())

    def test_alias_migration_and_ambiguous_suggestions(self):
        from catalog import aliases_for, set_aliases
        from classifier import suggest
        from inbox import build_inbox
        path = self.root / ".courseshelf.json"
        original = {"schema_version": 1, "courses": {"秋季/高等数学": {"categories": ["作业", "课件"]}}}
        path.write_text(json.dumps(original), encoding="utf-8")
        data = load_catalog(self.root)
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text()), original)
        self.assertEqual(data["courses"]["秋季/高等数学"]["categories"], ["作业", "课件"])
        set_aliases(self.root, "秋季", "高等数学", ["高数"])
        aliases = aliases_for(self.root)
        result = suggest("高数-第3章.pdf", ["高等数学"], ["课件"], aliases={"高等数学": ["高数"]})
        self.assertEqual((result.course, result.confidence), ("高等数学", "high"))
        ambiguous = suggest("高数.pdf", ["高等数学", "离散数学"], aliases={"高等数学": ["高数"], "离散数学": ["高数"]})
        self.assertIsNone(ambiguous.course)
        source = self.base / "高数-课件.pdf"
        source.write_text("material")
        item = build_inbox([source], ["秋季/高等数学"], {"秋季/高等数学": ["课件"]}, aliases=aliases)[0]
        self.assertEqual(item.suggested_course, "秋季/高等数学")
        self.assertIsNone(item.course, "a suggestion must not silently become a decision")
        approximate = suggest("数字信号处里-课件.pdf", ["数字信号处理"])
        self.assertEqual(approximate.confidence, "low")
        with patch("catalog._migrate", side_effect=ValueError("injected migration failure")):
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            self.assertTrue(load_catalog(self.root)["_read_only"])
            self.assertEqual(path.read_bytes(), before)

    def test_lazy_deep_tree_and_large_directory_responsiveness(self):
        import catalog
        create_plan(self.root, "秋季", ["数学"])
        deep = self.root / "秋季/数学/课件/第一章/例题"
        deep.mkdir(parents=True)
        for index in range(5000):
            (deep / f"file{index:04d}.txt").write_text("data")
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        wait_worker(window.scan_worker)
        with patch.object(catalog, "load_catalog", wraps=catalog.load_catalog) as loader:
            window.refresh_browser(preferred=str(deep))
        self.assertEqual(loader.call_count, 1)
        self.assertIn(deep, window.tree_items)
        started = time.perf_counter()
        window.show_files(deep)
        self.assertLess(time.perf_counter() - started, 0.2)
        gaps, last = [], [time.perf_counter()]
        loop = QEventLoop()
        timer = QTimer()
        def tick():
            current = time.perf_counter()
            gaps.append(current - last[0])
            last[0] = current
            if window.files_table.rowCount() == 5000 and window.files_table.item(4999, 0) is not None:
                loop.quit()
        timer.timeout.connect(tick)
        timer.start(10)
        QTimer.singleShot(15000, loop.quit)
        loop.exec()
        timer.stop()
        self.assertEqual(window.files_table.rowCount(), 5000)
        self.assertIsNotNone(window.files_table.item(4999, 0))
        self.assertLess(max(gaps), 0.2)
        print(f"V14: 5000 files, maximum event-loop gap {max(gaps) * 1000:.1f} ms")
        window.close()

    def test_settings_migration_and_file_actions(self):
        from history import manage_file
        from organizer import settings_path
        local = self.base / "appdata"
        legacy = local / "FilesOrganizerDemo"
        legacy.mkdir(parents=True)
        (legacy / "settings.json").write_text(json.dumps({"root": str(self.root)}), encoding="utf-8")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            os.environ.pop("FILES_ORGANIZER_CONFIG_DIR", None)
            self.assertEqual(settings_path(), local / "CourseShelf/settings.json")
            self.assertEqual(json.loads(settings_path().read_text())["root"], str(self.root))
            self.assertTrue((legacy / "settings.json").exists())
        items = self.prepare_batch()[:1]
        results, _ = self.run_batch(items)
        path = Path(results[0][1]["target"])
        manage_file(self.root, path, "rename", "renamed.pdf")
        renamed = path.with_name("renamed.pdf")
        self.assertTrue(renamed.is_file())
        manage_file(self.root, renamed, "trash")
        self.assertFalse(renamed.exists())
        unowned = self.root / "user-file.txt"
        unowned.write_text("never modify")
        with self.assertRaisesRegex(ValueError, "本应用"):
            manage_file(self.root, unowned, "trash")
        self.assertTrue(unowned.exists())

    def test_cached_ocr_offline_and_header_synonyms(self):
        from tests.smoke_demo import make_sample
        from services import ocr_process
        from organizer import _table_course_lines
        image = self.base / "sample.png"
        make_sample(image)
        timings, stages = [], []
        try:
            with patch.dict(os.environ, {"COURSESHELF_OFFLINE_TEST": "1"}):
                pids = []
                for _ in range(2):
                    started = time.perf_counter()
                    lines = ocr_process.recognize(image, lambda: False, stages.append)
                    timings.append(time.perf_counter() - started)
                    self.assertEqual(len(lines), 9)
                    pids.append(ocr_process._process.pid)
                self.assertEqual(pids[0], pids[1], "the model process must be reused")
                self.assertLess(timings[1], timings[0])
                self.assertTrue(any("复用" in stage for stage in stages))
        finally:
            ocr_process.stop()
        def box(x, y):
            return [[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]]
        texts = ["编号", "科目", "类型", "1", "示例课程"]
        boxes = [box(100, 20), box(250,20), box(400,20), box(30,60), box(250,60)]
        self.assertEqual(_table_course_lines(boxes, texts), ["示例课程"])
        print(f"U03 cached OCR: {timings[0]:.3f}s -> {timings[1]:.3f}s")

    def test_ocr_result_cache_checks_content(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from services import organizer
        image = self.base / "cache-input.png"
        image.write_bytes(b"first")
        original = image.stat()
        engine = Mock(side_effect=[SimpleNamespace(txts=["first"], boxes=None), SimpleNamespace(txts=["other"], boxes=None)])
        with patch.object(organizer, "_engine", engine), patch.object(organizer, "_result_cache", None):
            self.assertEqual(organizer.local_ocr(image), ["first"])
            self.assertEqual(organizer.local_ocr(image), ["first"])
            image.write_bytes(b"other")
            os.utime(image, ns=(original.st_atime_ns, original.st_mtime_ns))
            self.assertEqual(organizer.local_ocr(image), ["other"])
            self.assertEqual(engine.call_count, 2)

    def test_catalog_backup_link_blocks_writes_before_creation(self):
        create_plan(self.root, "秋季", ["数学"])
        backup = self.root / ".courseshelf.json.bak"
        backup.write_text("do not follow backup links")
        original = (self.root / ".courseshelf.json").read_bytes()
        is_link = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda path: path == backup or is_link(path)):
            with self.assertRaisesRegex(CatalogError, "备份路径"):
                create_plan(self.root, "new", ["other"])
        self.assertFalse((self.root / "new").exists())
        self.assertEqual((self.root / ".courseshelf.json").read_bytes(), original)
        self.assertEqual(backup.read_text(), "do not follow backup links")

    def test_numeric_sort_and_shell_location(self):
        create_plan(self.root, "秋季", ["数学"])
        target = self.root / "秋季/数学/课件"
        (target / "small.txt").write_bytes(b"a" * 9)
        (target / "large.txt").write_bytes(b"a" * 100)
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        window.show_files(target)
        from PySide6.QtCore import Qt
        window.files_table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(window.files_table.item(0, 0).text(), "small.txt")
        window.files_table.setCurrentCell(0, 0)
        with patch("ui.tabs.browser.subprocess.Popen") as locate:
            window.locate_selected_file()
        self.assertIn(str(target / "small.txt"), locate.call_args.args[0][1])
        window.close()

    def test_cross_process_instance_lock(self):
        import subprocess
        from organizer import settings_path
        lock_path = settings_path().parent / "app.lock"
        lock_path.parent.mkdir(exist_ok=True)
        program = "from PySide6.QtCore import QLockFile; import sys; lock=QLockFile(sys.argv[1]); lock.setStaleLockTime(0); print(lock.tryLock(0),flush=True); sys.stdin.read(); lock.unlock()"
        child = subprocess.Popen([sys.executable, "-c", program, str(lock_path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.assertEqual(child.stdout.readline().strip(), "True")
            with patch.object(QMessageBox, "information") as message:
                self.assertIsNone(acquire_instance())
            self.assertIn("已在运行", message.call_args.args[1])
        finally:
            child.stdin.close()
            child.wait(timeout=10)
            child.stdout.close()
        lock = acquire_instance()
        self.assertIsNotNone(lock)
        lock.unlock()

    def test_ui_all_failed_then_retry(self):
        items = self.prepare_batch()
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        window.add_to_inbox([item.source for item in items])
        for item in window.inbox_items:
            item.course, item.category = "秋季/数学", "课件"
        window.render_inbox()
        window.select_inbox_row(0)
        with patch("tasks.worker.transfer", side_effect=lambda *a, **k: (_ for _ in ()).throw(PermissionError("injected read-only target"))):
            window.archive_file()
            wait_worker(window.file_worker)
        self.assertTrue(all(item.status == "failed" for item in window.inbox_items))
        self.assertIn("失败 20", window.archive_status.text())
        window.retry_failed()
        wait_worker(window.file_worker)
        self.assertTrue(all(item.status == "ok" for item in window.inbox_items))
        self.assertEqual({Path(item.target).parent.name for item in window.inbox_items}, {"课件"})
        window.close()

    def test_category_actions_protect_unmanaged_and_changed_files(self):
        from catalog import rename_category, trash_category
        from history import owned_record
        from tasks import CategoryWorker
        items = self.prepare_batch()
        results, summary = self.run_batch(items[:1])
        self.assertEqual(summary["ok"], 1)
        target = Path(results[0][1]["target"])
        folder = target.parent
        unknown = folder / "user-note.txt"
        unknown.write_bytes(b"user material")
        original = (self.root / ".courseshelf.json").read_bytes()
        for action in (lambda: rename_category(self.root, "秋季", "数学", "课件", "新分类"),
                       lambda: trash_category(self.root, "秋季", "数学", "课件")):
            with self.assertRaisesRegex(CatalogError, "非本应用"):
                action()
        self.assertEqual(unknown.read_bytes(), b"user material")
        self.assertEqual((self.root / ".courseshelf.json").read_bytes(), original)
        unknown.unlink()  # Disposable test input, never application deletion.
        content = target.read_bytes()
        target.write_bytes(b"changed")
        with self.assertRaisesRegex(CatalogError, "内容已改变"):
            trash_category(self.root, "秋季", "数学", "课件")
        target.write_bytes(content)
        cancelled = CategoryWorker((self.root, "秋季", "数学"), "课件", "新分类")
        cancelled.request_cancel()
        cancelled.run()
        self.assertTrue(target.exists())
        renamed = rename_category(self.root, "秋季", "数学", "课件", "新分类")
        self.assertIsNotNone(owned_record(self.root, renamed / target.name))
        with patch("catalog.send2trash") as recycle:
            trash_category(self.root, "秋季", "数学", "新分类")
        recycle.assert_called_once_with(str(renamed))


if __name__ == "__main__":
    unittest.main()
