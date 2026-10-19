"""Appearance changes must persist locally without changing library contents."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QMimeData, QPointF, QPoint, QUrl
from PySide6.QtGui import QDropEvent

from app import MainWindow
from organizer import load_settings, save_settings
from services.preferences import load_preferences, normalize, save_preferences
from ui.appearance import AppearanceDialog
from ui.style import THEMES

APP = QApplication.instance() or QApplication([])


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="courseshelf-appearance-")
        self.base = Path(self.temp.name).resolve()
        self.environment = patch.dict(os.environ, {"FILES_ORGANIZER_CONFIG_DIR": str(self.base / "settings")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_preferences_survive_library_and_view_changes(self):
        prefs = dict(theme="ink", background=str(self.base / "picture.jpg"), visibility=50)
        save_preferences(prefs)
        root = self.base / "library"
        root.mkdir()
        save_settings(root, root)
        self.assertEqual(load_preferences(), prefs)
        self.assertEqual(load_settings()["root"], str(root))
        self.assertFalse(list((self.base / "settings").glob("*.tmp")))
        self.assertEqual(normalize({"theme": [], "visibility": "invalid"})["theme"], "paper")
        self.assertEqual(normalize({"visibility": 900})["visibility"], 80)
        (self.base / "settings/appearance.json").write_text("broken")
        self.assertEqual(load_preferences(), normalize({}))

    def test_theme_navigation_and_background_persist(self):
        image = self.base / "我的背景 image.png"
        Image.new("RGB", (900, 500), "#CDA977").save(image)
        original = image.read_bytes()
        window = MainWindow()
        dialog = AppearanceDialog(window, window.appearance)
        dialog.changed.connect(window.apply_appearance)
        for theme, colors in THEMES.items():
            dialog.theme_buttons[theme].click()
            self.assertEqual(window.appearance["theme"], theme)
            self.assertEqual(window.canvas.base.name().lower(), colors["base"].lower())
        self.assertTrue(dialog.set_background(str(image)))
        dialog.visibility.setValue(65)
        window.nav_buttons[4].click()
        self.assertEqual(window.tabs.currentIndex(), 4)
        window.tabs.setCurrentIndex(2)
        self.assertTrue(window.nav_buttons[2].isChecked())
        self.assertFalse(window.archive_details.content.isVisibleTo(window))
        window.archive_details.toggle.click()
        self.assertFalse(window.archive_details.content.isHidden())
        window.close()
        reopened = MainWindow()
        self.assertEqual(reopened.appearance, dict(theme="ink", background=str(image.resolve()), visibility=65))
        self.assertFalse(reopened.canvas.picture.isNull())
        self.assertEqual(image.read_bytes(), original)
        reopened.close()
        dialog.deleteLater()
        APP.processEvents()

    def test_bad_background_retains_previous_and_missing_image_falls_back(self):
        image = self.base / "background.png"
        Image.new("RGB", (200, 150), "#AABBAA").save(image)
        window = MainWindow()
        dialog = AppearanceDialog(window, window.appearance)
        dialog.changed.connect(window.apply_appearance)
        self.assertTrue(dialog.set_background(str(image)))
        corrupt = self.base / "bad.jpg"
        corrupt.write_bytes(b"invalid image")
        self.assertFalse(dialog.set_background(str(corrupt)))
        self.assertEqual(window.appearance["background"], str(image.resolve()))
        self.assertTrue(dialog.error.text())
        window.close()
        image.unlink()
        reopened = MainWindow()
        self.assertTrue(reopened.canvas.picture.isNull())
        self.assertIn("背景图不可用", reopened.statusBar().currentMessage())
        reopened.close()
        dialog.deleteLater()
        APP.processEvents()

    def test_restoring_appearance_only_changes_appearance(self):
        root = self.base / "library"
        root.mkdir()
        source = root / "untouched.txt"
        source.write_bytes(b"user material")
        save_settings(root, root)
        save_preferences(dict(theme="mist", background="", visibility=60))
        window = MainWindow()
        dialog = AppearanceDialog(window, window.appearance)
        dialog.changed.connect(window.apply_appearance)
        dialog.restore_defaults()
        window.save_appearance()
        self.assertEqual(load_preferences(), normalize({}))
        self.assertEqual(load_settings()["root"], str(root))
        self.assertEqual(source.read_bytes(), b"user material")
        from tests.test_improvement import wait_worker
        if window.scan_worker and window.scan_worker.isRunning():
            wait_worker(window.scan_worker)
        window.close()
        dialog.deleteLater()
        APP.processEvents()

    def test_compact_layout_drop_and_background_removal(self):
        image = self.base / "photo.png"
        Image.new("RGB", (100, 100), "#AABBCC").save(image)
        window = MainWindow()
        window.resize(1040, 720)
        window.tabs.setCurrentIndex(2)
        window.show()
        APP.processEvents()
        self.assertGreater(window.inbox_table.columnWidth(0), 130)
        button_bottom = window.copy_button.mapTo(window, QPoint(0, window.copy_button.height())).y()
        self.assertLessEqual(button_bottom, window.height())
        self.assertTrue(window.archive_details.toggle.isVisibleTo(window))
        files = [self.base / "one.txt", self.base / "two.txt"]
        for source in files:
            source.write_bytes(b"unchanged")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(source)) for source in files])
        event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        window.inbox_table.dropEvent(event)
        self.assertEqual(len(window.inbox_items), 2)
        self.assertTrue(window.copy_radio.isChecked())
        self.assertTrue(all(source.read_bytes() == b"unchanged" for source in files))
        dialog = AppearanceDialog(window, window.appearance)
        dialog.changed.connect(window.apply_appearance)
        dialog.set_background(str(image))
        dialog.set_background("")
        self.assertTrue(window.canvas.picture.isNull())
        self.assertTrue(image.exists())
        window.focus_search()
        self.assertEqual(window.tabs.currentIndex(), 4)
        window.close()
        dialog.deleteLater()
        APP.processEvents()
