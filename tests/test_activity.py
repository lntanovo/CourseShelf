"""The activity page shows existing audit records without mutating them or files."""
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView

from catalog import create_plan
from history import connect_history, history_path, read_operations, record
from tests import test_workflows
from tests.test_improvement import wait_worker


APP = test_workflows.APP


class ActivityTests(unittest.TestCase):
    setUp = test_workflows.WorkflowTests.setUp
    tearDown = test_workflows.WorkflowTests.tearDown
    window = test_workflows.WorkflowTests.window

    def test_missing_database_stays_missing(self):
        self.assertEqual(read_operations(self.root), [])
        self.assertFalse(history_path().exists())
        window = self.window()
        window.nav_buttons[4].click()
        self.assertEqual(window.history_table.rowCount(), 0)
        self.assertEqual(window.history_status.text(), "暂无操作记录")
        self.assertFalse(history_path().exists())

    def test_read_only_localized_records_and_file_protection(self):
        source = self.base / "notes.txt"
        source.write_bytes(b"do not change")
        destination = self.root / "notes.txt"
        destination.write_bytes(b"archived material")
        stamp = int(datetime(2026, 10, 21, 9, 30).timestamp() * 1e9)
        fixtures = [("mkdir", "ok"), ("copy", "ok"), ("move", "skipped"), ("rename", "failed"), ("trash", "partial")]
        for offset, (kind, result) in enumerate(fixtures):
            with patch("history.time.time_ns", return_value=stamp + offset * 1_000_000_000):
                record(self.root, kind, src=source, dst=destination, result=result, error="fixture reason")
        other = self.base / "other"
        other.mkdir()
        record(other, "mkdir", dst=other / "invisible")
        original = history_path().read_bytes()
        window = self.window()
        window.nav_buttons[4].click()
        table = window.history_table
        self.assertEqual(table.rowCount(), 5)
        self.assertEqual(table.item(0, 0).text(), "2026-10-21 09:30:04")
        self.assertEqual([table.item(row, 1).text() for row in range(5)], ["移至回收站", "重命名", "移动", "复制", "创建目录"])
        self.assertEqual([table.item(row, 3).text() for row in range(5)], ["部分完成", "失败", "已跳过", "成功", "成功"])
        self.assertIn("notes.txt", table.item(0, 2).text())
        self.assertIn(str(source), table.item(0, 2).toolTip())
        self.assertEqual(table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertFalse(any("撤销" in button.text() for button in window.findChildren(QAbstractButton)))
        self.assertFalse(hasattr(window, "undo_selected"))
        window.show()
        APP.processEvents()
        with patch("history.undo", side_effect=AssertionError("read-only page invoked undo")):
            rect = table.visualItemRect(table.item(0, 2))
            QTest.mouseDClick(table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            QTest.keyClick(table, Qt.Key.Key_Delete)
            window.refresh_history()
        self.assertEqual(history_path().read_bytes(), original)
        self.assertEqual(source.read_bytes(), b"do not change")
        self.assertEqual(destination.read_bytes(), b"archived material")

    def test_archiving_and_root_changes_refresh_visible_history(self):
        create_plan(self.root, "秋季", ["数学"])
        window = self.window()
        source = self.base / "数学-课件.txt"
        source.write_bytes(b"material")
        window.add_to_inbox([source])
        window.apply_suggestions()
        window.nav_buttons[4].click()
        window.archive_file()
        wait_worker(window.file_worker)
        self.assertEqual(window.history_table.item(0, 1).text(), "复制")
        self.assertEqual(window.history_table.item(0, 3).text(), "成功")
        other = self.base / "empty-library"
        other.mkdir()
        window.root_edit.setText(str(other))
        window.root_changed()
        self.assertEqual(window.history_table.rowCount(), 0)
        wait_worker(window.scan_worker)
        window.root_edit.setText(str(self.base / "missing"))
        window.root_changed()
        self.assertEqual(window.history_status.text(), "请选择资料库")

    def test_corrupt_and_future_history_are_preserved(self):
        window = self.window()
        path = history_path()
        path.write_bytes(b"corrupt history fixture")
        window.nav_buttons[4].click()
        self.assertIn("无法读取", window.history_status.text())
        self.assertEqual(path.read_bytes(), b"corrupt history fixture")
        path.unlink()  # Disposable fixture only; the display code never removes it.
        record(self.root, "mkdir", dst=self.root / "existing")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA user_version=99")
        original = path.read_bytes()
        window.refresh_history()
        self.assertIn("版本不支持", window.history_status.text())
        self.assertEqual(window.history_table.rowCount(), 0)
        self.assertEqual(path.read_bytes(), original)

    def test_recent_records_are_bounded_and_newest_first(self):
        with closing(connect_history()) as connection, connection:
            connection.executemany("INSERT INTO operation(library,batch_id,kind,result,ts) VALUES(?,?,?,?,?)",
                                   [(str(self.root), "fixture", "copy", "ok", stamp) for stamp in range(510)])
        original = history_path().read_bytes()
        rows = read_operations(self.root, limit=1000)
        self.assertEqual(len(rows), 500)
        self.assertEqual((rows[0]["ts"], rows[-1]["ts"]), (509, 10))
        self.assertEqual(history_path().read_bytes(), original)
