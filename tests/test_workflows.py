"""User-facing workflow regressions use fictional courses and disposable files."""
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QItemSelectionModel, QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QAbstractButton, QGroupBox

from app import MainWindow
from catalog import CatalogError, create_plan, load_catalog
from library_index import scan, search
from runtime import configure_logging, log
from services.browser import library_ancestor
from services.query_dates import time_window
from tests.test_improvement import wait_worker

APP = QApplication.instance() or QApplication([])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="courseshelf-workflows-")
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "library"
        self.root.mkdir()
        self.environment = patch.dict(os.environ, {"FILES_ORGANIZER_CONFIG_DIR": str(self.base / "settings")})
        self.environment.start()
        configure_logging()
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            for worker in (window.file_worker, window.scan_worker, *window._directory_workers):
                if worker and worker.isRunning():
                    worker.request_cancel()
                    wait_worker(worker)
            window.close()
        APP.processEvents()
        for handler in list(log.handlers):
            log.removeHandler(handler)
            handler.close()
        self.environment.stop()
        self.temp.cleanup()

    def window(self):
        window = MainWindow()
        self.windows.append(window)
        window.root_edit.setText(str(self.root))
        window.root_changed()
        if window.scan_worker.isRunning():
            wait_worker(window.scan_worker)
        return window

    def test_course_double_click_editor_has_readable_height(self):
        window = self.window()
        window._add_course_item("示例课程名称比较长仍然能够完整编辑")
        window.tabs.setCurrentIndex(0)
        window.show()
        APP.processEvents()
        item = window.courses_list.item(0)
        rect = window.courses_list.visualItemRect(item)
        QTest.mouseClick(window.courses_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        QTest.mouseDClick(window.courses_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        APP.processEvents()
        editor = window.courses_list.findChild(QLineEdit, "courseEditor")
        self.assertIsNotNone(editor)
        self.assertGreaterEqual(editor.height(), editor.fontMetrics().height() + 6)
        self.assertTrue(rect.contains(editor.geometry()))
        editor.setText("修改后的示例课程")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        APP.processEvents()
        self.assertEqual(item.text(), "修改后的示例课程")
        self.assertEqual(window.course_hint.text(), "1 门课程")
        self.assertFalse(window.root_status.isVisible())

    def test_removed_features_leave_working_navigation_and_preserve_existing_data(self):
        from catalog import set_aliases
        from history import operations
        create_plan(self.root, "秋季", ["数学"])
        set_aliases(self.root, "秋季", "数学", ["旧版简称"])
        original_file = self.root / "秋季/数学/课件/original.txt"
        original_file.write_bytes(b"existing user material")
        metadata = (self.root / ".courseshelf.json").read_bytes()
        record_ids = [record["id"] for record in operations(self.root)]
        window = self.window()
        self.assertEqual(window.tabs.count(), 5)
        for index, title in enumerate(("课表与课程", "生成目录", "整理资料", "资料库", "操作记录")):
            window.nav_buttons[index].click()
            self.assertEqual(window.tabs.currentIndex(), index)
            self.assertEqual(window.page_heading.text(), title)
        texts = [button.text() for button in window.findChildren(QAbstractButton)]
        texts += [box.title() for box in window.findChildren(QGroupBox)]
        texts += [window.tabs.tabText(index) for index in range(window.tabs.count())]
        for removed in ("撤销选中操作", "选中项详情与进阶选项", "管理分类与课程别名",
                        "纳入管理", "编辑课程别名", "把本次选择记为别名…"):
            self.assertNotIn(removed, texts)
        self.assertEqual(window.inbox_table.columnCount(), 6)
        self.assertEqual((self.root / ".courseshelf.json").read_bytes(), metadata)
        self.assertEqual([record["id"] for record in operations(self.root)], record_ids)
        self.assertEqual(original_file.read_bytes(), b"existing user material")

    def test_tree_preview_and_scoped_categories_do_not_write_before_generate(self):
        window = self.window()
        for name in ("数学", "设计"):
            window._add_course_item(name)
        window.semester_edit.setText("秋季")
        window.plan_category_name.setEditText("课设")
        window.add_plan_category()
        window.plan_scope.setCurrentIndex(window.plan_scope.findData("设计"))
        window.plan_category_name.setEditText("杂项")
        window.add_plan_category()
        top = window.preview.topLevelItem(0)
        self.assertEqual(top.childCount(), 2)
        self.assertFalse(top.child(0).isExpanded())
        self.assertEqual(top.child(0).childCount(), 5)
        self.assertEqual(top.child(1).childCount(), 6)
        self.assertEqual(window.preview.path_count(), 14)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertTrue(window.generate())
        self.assertTrue((self.root / "秋季/数学/课设").is_dir())
        self.assertFalse((self.root / "秋季/数学/杂项").exists())
        self.assertTrue((self.root / "秋季/设计/杂项").is_dir())
        self.assertIn("课设", load_catalog(self.root)["courses"]["秋季/数学"]["categories"])
        self.assertTrue(window.generate())
        self.assertIn("创建 0", window.generate_status.text())

    def test_custom_category_validation_and_partial_success(self):
        with self.assertRaises(CatalogError):
            create_plan(self.root, "invalid", ["数学"], extra_categories={"数学": ["../escape"]})
        self.assertFalse((self.root / "invalid").exists())
        create_plan(self.root, "秋季", ["数学", "设计"])
        blocked = self.root / "秋季/数学/课设"
        blocked.write_bytes(b"keep user file")
        _, _, failures, _ = create_plan(self.root, "秋季", ["数学", "设计"],
                                        extra_categories={"数学": ["课设"], "设计": ["课设"]})
        self.assertEqual(len(failures), 1)
        self.assertEqual(blocked.read_bytes(), b"keep user file")
        data = load_catalog(self.root)["courses"]
        self.assertNotIn("课设", data["秋季/数学"]["categories"])
        self.assertIn("课设", data["秋季/设计"]["categories"])

    def test_multi_select_target_and_execute_only_ready_rows(self):
        create_plan(self.root, "秋季", ["数学", "设计"])
        window = self.window()
        sources = [self.base / f"unknown-{i}.txt" for i in range(3)]
        for source in sources:
            source.write_bytes(source.name.encode())
        window.add_to_inbox(sources)
        window.inbox_table.clearSelection()
        for row in (0, 1):
            window.inbox_table.selectionModel().select(window.inbox_table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        window.course_combo.setCurrentText("数学")
        window.category_combo.setCurrentText("课件")
        self.assertTrue(all(item.course is None for item in window.inbox_items))
        window.apply_batch_target()
        self.assertEqual([item.course for item in window.inbox_items], ["秋季/数学", "秋季/数学", None])
        category = window.inbox_table.cellWidget(0, 3)
        category.setCurrentIndex(0)
        self.assertEqual(window.inbox_table.item(0, 5).text(), "需选目标")
        category.setCurrentIndex(category.findData("课件"))
        self.assertEqual(window.inbox_table.item(0, 5).text(), "待执行")
        window.execute_scope.setCurrentIndex(window.execute_scope.findData("selected"))
        self.assertEqual(window.copy_button.text(), "执行 2 项")
        window.archive_file()
        wait_worker(window.file_worker)
        self.assertEqual([item.status for item in window.inbox_items], ["ok", "ok", "pending"])
        self.assertIn("1 项需选目标", window.archive_status.text())
        self.assertEqual(window.copy_button.text(), "执行 0 项")
        self.assertFalse(window.copy_button.isEnabled())
        self.assertTrue(all(source.exists() for source in sources))
        self.assertFalse(window.inbox_table.cellWidget(0, 2).isEnabled())

    def test_paste_commits_on_enter_and_suggestions_preserve_manual_target(self):
        create_plan(self.root, "秋季", ["数学", "设计"])
        window = self.window()
        one, two = self.base / "first.txt", self.base / "数学-课件.txt"
        one.write_text("first")
        two.write_text("second")
        window.add_to_inbox([one])
        window.source_edit.setText(str(self.base / "partial-path"))
        APP.processEvents()
        self.assertEqual(len(window.inbox_items), 1)
        window.source_edit.setText(str(two))
        window.source_edit.returnPressed.emit()
        self.assertEqual(len(window.inbox_items), 2)
        item = window.inbox_items[1]
        self.assertIsNone(item.course)
        item.course, item.category = "秋季/设计", None
        window.apply_suggestions()
        self.assertEqual(item.course, "秋季/设计")
        self.assertIsNone(item.category)

    def test_calendar_filters_exact_terms_and_scope(self):
        for term in ("春季", "秋季"):
            create_plan(self.root, term, ["数学"])
        today = date.today()
        lower, upper = time_window("today", today=today)
        records = [("秋季/数学/课件/today.txt", lower + 1_000_000_000),
                   ("秋季/数学/作业/last-day.txt", lower - 1_000_000_000),
                   ("春季/数学/课件/other-term.txt", lower + 2_000_000_000),
                   ("秋季/数学/课件/next-day.txt", upper)]
        for name, stamp in records:
            path = self.root / name
            path.write_bytes(b"data")
            os.utime(path, ns=(stamp, stamp))
        scan(self.root)
        found = search(self.root, course="数学", semester="秋季", category="课件", exact=True,
                       modified_from=lower, modified_before=upper)
        self.assertEqual([row["name"] for row in found], ["today.txt"])
        self.assertEqual(search(self.root, course="数", exact=True), [])
        self.assertEqual(len(search(self.root, scope=self.root / "秋季/数学")), 3)
        self.assertEqual(search(self.root, limit=1, sort="newest")[0]["name"], "next-day.txt")
        self.assertEqual(time_window("custom", today, today), (lower, upper))
        with self.assertRaises(ValueError):
            time_window("custom", today, today - timedelta(days=1))
        with self.assertRaises(ValueError):
            search(self.root, scope=self.root.parent)

    def test_dropdown_filters_refresh_and_invalid_dates(self):
        create_plan(self.root, "秋季", ["数学"], extra_categories={"数学": ["课设"]})
        target = self.root / "秋季/数学/课设/today.txt"
        target.write_text("current")
        window = self.window()
        window.search_term.setCurrentIndex(window.search_term.findData("秋季"))
        window.search_course.setCurrentIndex(window.search_course.findData("秋季/数学"))
        window.search_category.setCurrentIndex(window.search_category.findData("课设"))
        window.search_time.setCurrentIndex(window.search_time.findData("today"))
        window.search_files()
        self.assertEqual(window.files_table.rowCount(), 1)
        self.assertEqual(window.files_table.item(0, 0).text(), "today.txt")
        second = target.with_name("new.txt")
        second.write_text("new")
        window.refresh_browser()
        wait_worker(window.scan_worker)
        self.assertEqual(window.search_category.currentData(), "课设")
        self.assertEqual(window.files_table.rowCount(), 2)
        window.search_time.setCurrentIndex(window.search_time.findData("custom"))
        window.date_from.setDate(QDate.currentDate())
        window.date_until.setDate(QDate.currentDate().addDays(-1))
        window.search_files()
        self.assertEqual(window.files_table.rowCount(), 0)
        self.assertIn("结束日期", window.index_status.text())
        window.reset_search()
        self.assertEqual(window.search_category.currentIndex(), 0)
        self.assertEqual(window.files_table.rowCount(), 2)
        self.assertNotIn("结束日期", window.index_status.text())

    def test_child_folder_selection_keeps_library_root_after_confirmation(self):
        create_plan(self.root, "秋季", ["数学"])
        child = self.root / "秋季/数学/课件"
        self.assertEqual(library_ancestor(child), self.root)
        original = (self.root / ".courseshelf.json").read_bytes()
        window = self.window()
        window.root_edit.setText(str(child))
        with patch.object(QMessageBox, "exec", lambda box: box.buttons()[0].click()):
            window.root_changed()
        self.assertEqual(window.root_path(), self.root)
        self.assertEqual(window.current_directory, child)
        self.assertEqual(window.tabs.currentIndex(), 3)
        self.assertFalse((child / ".courseshelf.json").exists())
        self.assertEqual((self.root / ".courseshelf.json").read_bytes(), original)
