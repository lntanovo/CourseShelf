"""Render review screenshots with fictional files and a temporary wallpaper."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
from app import MainWindow
from catalog import create_plan
from ui.style import THEMES
from tests.test_improvement import wait_worker


def main():
    output = Path(__file__).resolve().parents[1] / "artifacts/ui-refresh"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    def settle():
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
    with tempfile.TemporaryDirectory(prefix="courseshelf-ui-preview-") as temporary:
        base = Path(temporary).resolve()
        os.environ["FILES_ORGANIZER_CONFIG_DIR"] = str(base / "settings")
        root = base / "我的课程资料"
        root.mkdir()
        create_plan(root, "2026 秋季", ["设计基础", "高等数学", "大学英语"])
        sources = []
        for name in ["设计基础-课件.pdf", "高等数学-作业.docx", "大学英语-阅读.txt", "待核对的笔记.txt"]:
            path = base / name
            path.write_text("fictional UI fixture", encoding="utf-8")
            sources.append(path)
        background = base / "preview-background.png"
        picture = Image.new("RGB", (1440, 960))
        draw = ImageDraw.Draw(picture)
        for y in range(960):
            draw.line((0, y, 1440, y), fill=(150 + y // 20, 174 + y // 28, 155 + y // 32))
        draw.ellipse((450, -160, 1500, 800), fill="#D7BB95")
        draw.ellipse((-500, 400, 1000, 1800), fill="#6B8E7E")
        picture.save(background)
        window = MainWindow()
        window.root_edit.setText(str(root))
        window.root_changed()
        wait_worker(window.scan_worker)
        window.add_to_inbox(sources)
        window.apply_suggestions()
        window.tabs.setCurrentIndex(2)
        window.show()
        for theme in THEMES:
            window.apply_appearance(dict(theme=theme, background="", visibility=35), persist=False)
            settle()
            assert window.grab().save(str(output / f"{theme}-inbox.png"))
        window.apply_appearance(dict(theme="paper", background=str(background), visibility=65), persist=False)
        settle()
        assert window.grab().save(str(output / "background.png"))
        window.open_appearance()
        settle()
        assert window._appearance_dialog.grab().save(str(output / "appearance.png"))
        window._appearance_dialog.close()
        settle()
        window.resize(1040, 720)
        settle()
        assert window.grab().save(str(output / "compact.png"))
        window.archive_details.toggle.click()
        settle()
        assert window.grab().save(str(output / "compact-details.png"))
        window.tabs.setCurrentIndex(4)
        settle()
        assert window.grab().save(str(output / "library.png"))
        window.close()
        app.processEvents()
    print("Fictional UI previews:", output)


if __name__ == "__main__":
    main()
