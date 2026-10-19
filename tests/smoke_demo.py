"""End-to-end local smoke test using the supplied timetable screenshot."""

import os
import json
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

if not os.environ.get("FILES_ORGANIZER_NATIVE_UI_TEST"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app import MainWindow
from organizer import CATEGORIES, build_plan, load_settings, preview_paths, settings_path


EXPECTED_COURSES = [
    "通信原理", "数字信号处理", "通信电路与系统", "工程导论",
    "信息工程基础实验", "形势与政策", "毛泽东思想和中国特色社会主义理论体系概论",
    "信息导论", "专业实习",
]


def make_sample(path: Path) -> None:
    """Create a fictional timetable so the public test needs no personal screenshot."""
    font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "msyh.ttc"
    font = ImageFont.truetype(str(font_path), 25)
    heading = ImageFont.truetype(str(font_path), 31)
    picture = Image.new("RGB", (2300, 1000), "white")
    draw = ImageDraw.Draw(picture)
    draw.text((70, 25), "示例课表 · 虚构课程数据", fill="black", font=heading)
    columns = (65, 230, 770, 1640, 2220)
    for x in columns:
        draw.line((x, 100, x, 915), fill="#5d8bc6", width=2)
    for y in range(100, 916, 81):
        draw.line((65, y, 2220, y), fill="#5d8bc6", width=2)
    for x, label in ((105, "序号"), (320, "课程代码"), (1000, "课程名称"), (1810, "课程类别")):
        draw.text((x, 124), label, fill="black", font=font)
    for number, course in enumerate(EXPECTED_COURSES, 1):
        y = 124 + number * 81
        draw.text((125, y), str(number), fill="black", font=font)
        draw.text((300, y), f"C{number:04d}", fill="black", font=font)
        draw.text((790, y), course, fill="black", font=font)
        draw.text((1800, y), "示例课程", fill="black", font=font)
    picture.save(path)


def main():
    work = Path(tempfile.mkdtemp(prefix="FilesOrganizerDemo-"))
    sample = work / "sample-timetable.png"
    make_sample(sample)
    root = work / "资料"
    root.mkdir()
    os.environ["FILES_ORGANIZER_CONFIG_DIR"] = str(work / "settings")
    app = QApplication([])
    window = MainWindow()
    window.show()
    assert not window.ocr_button.isEnabled()
    assert window.grab().save(str(work / "ui-buttons-initial.png"))
    window.set_image(sample)
    assert window.ocr_button.isEnabled()

    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    with patch.object(socket.socket, "connect", side_effect=AssertionError("OCR attempted network access")):
        window.start_ocr()
        assert not window.ocr_button.isEnabled()
        app.processEvents()
        assert window.grab().save(str(work / "ui-buttons-recognizing.png"))
        window.worker.finished.connect(loop.quit)
        timer.start(30000)
        loop.exec()
        app.processEvents()
    assert not window.worker.isRunning(), "OCR timed out"
    assert window.ocr_button.isEnabled()
    expected = EXPECTED_COURSES
    assert window.course_names() == expected, window.course_names()
    print("OCR: 9/9 table courses found; socket access blocked")

    # Exercise correction and add/delete controls, then restore the verified list.
    window.courses_list.item(3).setText("工程导沦")
    window.courses_list.item(3).setText("工程导论")
    window.new_course.setText("临时课程")
    window.add_course()
    window.courses_list.setCurrentRow(window.courses_list.count() - 1)
    window.delete_course()
    assert window.course_names() == expected
    window.root_edit.setText(str(root))
    window.root_changed()
    window.semester_edit.setText("2026秋季学期")
    assert window.show_preview()
    assert window.preview.count() == 46
    window.generate()
    assert "创建 46" in window.generate_status.text(), window.generate_status.text()
    for _, course_dir in build_plan(root, "2026秋季学期", expected)[1]:
        assert all((course_dir / category).is_dir() for category in CATEGORIES)
    window.generate()
    assert "创建 0，已存在 46，失败 0" in window.generate_status.text(), window.generate_status.text()
    print("Directories: 46 created, second run reused all 46")

    source = work / "讲义.txt"
    source.write_text("original material", encoding="utf-8")
    window.source_edit.setText(str(source))
    window.course_combo.setCurrentText("通信原理")
    window.category_combo.setCurrentText("课件")
    assert str(root / "2026秋季学期" / "通信原理" / "课件") in window.destination_label.text()
    assert window.copy_button.isEnabled()
    window.tabs.setCurrentIndex(2)
    app.processEvents()
    assert window.grab().save(str(work / "ui-copy-before.png"))
    window.copy_button.click()
    loop = QEventLoop()
    window.file_worker.finished.connect(loop.quit)
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    assert window.archive_status.text().startswith("复制成功"), window.archive_status.text()
    app.processEvents()
    assert window.grab().save(str(work / "ui-copy-after.png"))
    # A second explicit enqueue exercises same-name protection in the unified inbox.
    window.add_to_inbox([source], replace=True)
    window.course_combo.setCurrentText("通信原理")
    window.category_combo.setCurrentText("课件")
    window.archive_file()
    loop = QEventLoop()
    window.file_worker.finished.connect(loop.quit)
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    assert "跳过 1" in window.archive_status.text(), window.archive_status.text()
    assert window.copy_button.isEnabled(), "copy button became disabled after successful copy"
    target = root / "2026秋季学期" / "通信原理" / "课件"
    assert (target / "讲义.txt").read_text(encoding="utf-8") == "original material"
    assert not (target / "讲义 (1).txt").exists(), "identical content should be skipped"
    assert source.read_text(encoding="utf-8") == "original material"
    with patch("os.startfile") as open_folder:
        window.open_destination()
        open_folder.assert_called_once_with(target)
    assert window.current_directory == target
    assert window.files_table.rowCount() == 1
    assert window.folder_tree.topLevelItemCount() == 1
    assert window.tree_items.get(target) is not None
    for tab, name in enumerate(("ocr", "generate", "archive")):
        window.tabs.setCurrentIndex(tab)
        app.processEvents()
        assert window.grab().save(str(work / f"ui-{name}.png"))
    print("Copy: source retained, identical duplicate skipped, prior target unchanged")

    assert load_settings()["root"] == str(root)
    window.close()
    reopened = MainWindow()
    assert reopened.root_edit.text() == str(root)
    assert reopened.current_directory == target
    assert reopened.files_table.rowCount() == 1
    assert reopened.tree_items.get(target) is not None
    reopened.close()
    print("Restart: root, selected directory, and existing files restored")

    missing = work / "missing-root"
    settings_path().write_text(json.dumps({"root": str(missing)}), encoding="utf-8")
    with patch.object(QMessageBox, "warning") as warning:
        invalid = MainWindow()
        app.processEvents()
        assert invalid.root_edit.text() == str(missing)
        assert not missing.exists()
        assert warning.called
        invalid.close()
    print("Missing remembered root: warning shown, path not recreated")

    # A collision after Windows-name cleaning must stop the operation.
    try:
        preview_paths(root, "test", ["课程?", "课程*"])
    except ValueError as exc:
        assert "清洗后同名" in str(exc)
    else:
        raise AssertionError("cleaned-name collision was silently merged")
    print("Name collision: rejected")
    print("TEST_DIRECTORY=" + str(work))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--make-sample":
        make_sample(Path(sys.argv[2]))
    else:
        main()
