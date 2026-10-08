"""Filesystem and UI acceptance checks use disposable directories only."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QMimeData, QPointF, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from app import MainWindow
from catalog import (add_category, categories_for, create_plan, disk_categories, import_course,
                     missing_paths, rename_category, restore_defaults, restore_missing, trash_category)
from classifier import suggest
from file_ops import Cancelled, PartialMoveError, transfer
from uninstaller import digest, uninstall

APP = QApplication.instance() or QApplication([])


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="courseshelf-accept-")
        self.base = Path(self.temp.name)
        self.root = self.base / "资料"
        self.root.mkdir()
        os.environ["FILES_ORGANIZER_CONFIG_DIR"] = str(self.base / "settings")

    def tearDown(self):
        self.temp.cleanup()

    def test_catalog_categories_missing_and_external(self):
        made, existing, failures, _ = create_plan(self.root, "秋季", ["通信原理", "数字信号处理"])
        self.assertEqual((made, existing, failures), (11, 0, []))
        course = self.root / "秋季" / "通信原理"
        other = self.root / "秋季" / "数字信号处理"
        add_category(self.root, "秋季", "通信原理", "实验")
        (course / "实验" / "data.txt").write_text("keep", encoding="utf-8")
        rename_category(self.root, "秋季", "通信原理", "实验", "实验资料")
        self.assertEqual((course / "实验资料" / "data.txt").read_text(encoding="utf-8"), "keep")
        rename_category(self.root, "秋季", "通信原理", "实验资料", "实验资料")
        add_category(self.root, "秋季", "通信原理", "Lab")
        (course / "Lab" / "case.txt").write_text("case")
        rename_category(self.root, "秋季", "通信原理", "Lab", "LAB")
        self.assertEqual((course / "LAB" / "case.txt").read_text(), "case")
        self.assertFalse((other / "实验资料").exists())
        trash_category(self.root, "秋季", "通信原理", "实验资料")
        self.assertFalse((course / "实验资料").exists())
        self.assertNotIn("实验资料", categories_for(self.root, "秋季", "通信原理"))
        made, _, failures, _ = create_plan(self.root, "秋季", ["通信原理"])
        self.assertEqual((made, failures), (0, []))
        self.assertFalse((course / "实验资料").exists())
        (course / "课件").rmdir()
        self.assertIn(course / "课件", missing_paths(self.root))
        self.assertFalse((course / "课件").exists())
        restore_missing(self.root, course / "课件")
        self.assertTrue((course / "课件").is_dir())
        (course / "额外").mkdir()
        self.assertIn("额外", disk_categories(self.root, "秋季", "通信原理"))
        import_course(self.root, "秋季", "通信原理")
        self.assertIn("额外", categories_for(self.root, "秋季", "通信原理"))
        print("A03 A08 A09: 分类变更、回收站、外部缺失和旧目录纳入管理通过")

    def test_legacy_course_is_not_silently_changed(self):
        legacy = self.root / "旧学期" / "旧课程"
        (legacy / "已有分类").mkdir(parents=True)
        made, _, failures, _ = create_plan(self.root, "旧学期", ["旧课程"])
        self.assertEqual((made, failures), (0, []))
        self.assertEqual(disk_categories(self.root, "旧学期", "旧课程"), ["已有分类"])
        self.assertEqual(categories_for(self.root, "旧学期", "旧课程"), ["已有分类"])
        from catalog import is_managed
        self.assertFalse(is_managed(self.root, "旧学期", "旧课程"))
        import_course(self.root, "旧学期", "旧课程")
        self.assertTrue(is_managed(self.root, "旧学期", "旧课程"))

    def test_suggestion_and_transfer(self):
        target = self.root / "秋季" / "通信原理" / "课件"
        target.mkdir(parents=True)
        result = suggest("通信原理-PPT-01.pdf", ["通信原理", "数字信号处理"], ["课件", "其他"])
        self.assertEqual((result.course, result.category), ("通信原理", "课件"))
        self.assertIsNone(suggest("资料.pdf", ["通信原理"], ["其他"]).course)
        self.assertIsNone(suggest("高等数学-离散数学.pdf", ["高等数学", "离散数学"], ["其他"]).course)
        src = self.base / "通信原理-PPT-01.pdf"
        src.write_bytes(b"course data" * 1000)
        one = transfer(src, target, root=self.root)
        two = transfer(src, target, root=self.root)
        self.assertEqual(two.name, "通信原理-PPT-01 (1).pdf")
        self.assertEqual(src.read_bytes(), one.read_bytes())
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with self.assertRaises(Cancelled):
            transfer(src, target, root=self.root, cancelled=lambda: True)
        self.assertEqual(list(target.glob(".courseshelf-partial-*")), [])
        with patch("file_ops.os.fsync", side_effect=OSError("injected write failure")):
            with self.assertRaises(OSError):
                transfer(src, target, root=self.root, mode="move")
        self.assertTrue(src.exists())
        original_unlink = Path.unlink
        def fail_source(path, *args, **kwargs):
            if path == src:
                raise PermissionError("injected source failure")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_source):
            with self.assertRaises(PartialMoveError) as caught:
                transfer(src, target, root=self.root, mode="move")
        self.assertTrue(caught.exception.target.is_file())
        self.assertTrue(src.is_file())
        movable = self.base / "待移动.txt"
        movable.write_text("move safely")
        moved = transfer(movable, target, root=self.root, mode="move")
        self.assertEqual(moved.read_text(), "move safely")
        self.assertFalse(movable.exists())
        print("A04 A05 A06 A07: 建议、同名复制、取消及移动故障保护通过")

    def test_ui_state_and_image_validation(self):
        window = MainWindow()
        window.show()
        try:
            valid = self.base / "table.png"
            from PIL import Image
            Image.new("RGB", (300, 200), "white").save(valid)
            def drop(paths):
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
                window.thumbnail.dropEvent(QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction,
                                                      mime, Qt.MouseButton.LeftButton,
                                                      Qt.KeyboardModifier.NoModifier))
            drop([valid])
            self.assertEqual(window.image_path, valid)
            bad = self.base / "bad.txt"
            bad.write_text("bad")
            drop([bad])
            drop([valid, bad])
            self.assertEqual(window.image_path, valid)
            window.root_edit.setText(str(self.root))
            window.root_changed()
            window.semester_edit.setText("秋季")
            window._add_course_item("通信原理")
            self.assertTrue(window.show_preview())
            self.assertFalse((self.root / "秋季").exists())
            with patch.object(QMessageBox, "exec", return_value=0):
                window.advance_to_archive()
            self.assertFalse((self.root / "秋季").exists())
            self.assertEqual(window.tabs.currentIndex(), 0)
            with patch.object(QMessageBox, "exec", lambda box: box.buttons()[0].click()):
                window.advance_to_archive()
            self.assertEqual(window.tabs.currentIndex(), 2)
            self.assertTrue((self.root / "秋季" / "通信原理" / "课件").is_dir())
            self.assertTrue(window.grab().save(str(self.base / "ui.png")))
            print("A01 A02 A11: 图片校验、生成确认门槛和窗口绘制通过")
        finally:
            window.close()

    def test_uninstall_preserves_unlisted_files_and_data(self):
        release = self.base / "relocated-release"
        release.mkdir()
        internal = release / "_internal"
        internal.mkdir()
        program = internal / "component.bin"
        program.write_bytes(b"application")
        owned = {"path": "_internal/component.bin", "sha256": digest(program)}
        (release / "release-manifest.json").write_text(json.dumps({"schema_version": 1, "files": [owned]}), encoding="utf-8")
        user_folder = release / "personal-materials"
        user_folder.mkdir()
        (user_folder / "my-note.txt").write_text("do not delete")
        empty_user_folder = release / "my-empty-folder"
        empty_user_folder.mkdir()
        report = uninstall(release)
        self.assertFalse(report["failed"])
        self.assertFalse(program.exists())
        self.assertFalse(internal.exists())
        self.assertTrue((user_folder / "my-note.txt").is_file())
        self.assertTrue(empty_user_folder.is_dir())
        print("A10: 清单式卸载保留用户资料和用户新建空目录")

    def test_missing_restart_and_live_suggestion(self):
        create_plan(self.root, "秋季", ["通信原理", "数字信号处理"])
        course = self.root / "秋季" / "通信原理"
        window = MainWindow()
        window.root_edit.setText(str(self.root))
        window.root_changed()
        missing = course / "课件"
        missing.rmdir()
        window.refresh_browser()
        self.assertIn("缺失", window.missing_label.text())
        self.assertFalse(missing.exists())
        window.close()
        reopened = MainWindow()
        try:
            self.assertEqual(reopened.root_path(), self.root)
            self.assertIn("缺失", reopened.missing_label.text())
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                index = reopened.missing_combo.findData(str(missing))
                reopened.missing_combo.setCurrentIndex(index)
                reopened.restore_missing_ui()
            self.assertTrue(missing.is_dir())
            self.assertEqual(list(missing.iterdir()), [])
            extra = course / "外部分类"
            extra.mkdir()
            (extra / "existing.txt").write_text("disk file")
            reopened.refresh_browser(preferred=str(extra))
            reopened.course_combo.setCurrentText("通信原理")
            self.assertIn("外部分类", [reopened.category_combo.itemText(i) for i in range(reopened.category_combo.count())])
            self.assertEqual(reopened.files_table.rowCount(), 1)
            src = self.base / "通信原理-PPT.pdf"
            src.write_text("source")
            reopened.source_edit.setText(str(src))
            self.assertEqual(reopened.course_combo.currentText(), "通信原理")
            self.assertEqual(reopened.category_combo.currentText(), "课件")
            self.assertIn("文件名包含课程全名", reopened.suggestion_label.text())
            ambiguous = self.base / "模糊材料.pdf"
            ambiguous.write_text("source")
            reopened.source_edit.setText(str(ambiguous))
            self.assertEqual(reopened.course_combo.currentIndex(), -1)
            self.assertIn("需手动选择", reopened.suggestion_label.text())
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
