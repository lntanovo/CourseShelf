"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QWidget,
)

from organizer import extract_candidates
from runtime import (log)


from tasks import OcrWorker
from ui.widgets import ImageDropZone, CourseDelegate

class OcrMixin:
    def _make_ocr_tab(self) -> QWidget:
        scroll, layout = self._scroll_content()
        image_card, image_layout = self._card("导入课表图片")
        self.image_label = QLabel("尚未选择图片")
        self.image_label.setObjectName("pathText")
        self.image_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.image_label.setWordWrap(True)
        image_layout.addWidget(self.image_label)
        self.thumbnail = ImageDropZone()
        self.thumbnail.clicked.connect(self.choose_image)
        self.thumbnail.image_dropped.connect(lambda raw: self.set_image(Path(raw)))
        image_layout.addWidget(self.thumbnail)
        row = QHBoxLayout()
        row.addWidget(self._button("选择课表图片", self.choose_image))
        self.ocr_button = self._button("开始本地识别", self.start_ocr, True)
        self.ocr_button.setEnabled(False)
        row.addWidget(self.ocr_button)
        self.cancel_ocr_button = self._button("取消识别", self.cancel_ocr)
        self.cancel_ocr_button.setVisible(False)
        row.addWidget(self.cancel_ocr_button)
        row.addStretch()
        image_layout.addLayout(row)
        self.ocr_progress = QProgressBar()
        self.ocr_progress.setTextVisible(False)
        self.ocr_progress.setVisible(False)
        image_layout.addWidget(self.ocr_progress)
        self.ocr_status = QLabel("")
        self.thumbnail.rejected.connect(self.ocr_status.setText)
        self.ocr_status.setWordWrap(True)
        image_layout.addWidget(self.ocr_status)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        columns.addWidget(image_card, 1)

        course_card, course_layout = self._card("核对课程名称")
        self.course_hint = QLabel("0 门课程")
        self.course_hint.setWordWrap(True)
        course_layout.addWidget(self.course_hint)
        self.courses_list = QListWidget()
        self.courses_list.setItemDelegate(CourseDelegate(self.courses_list))
        self.courses_list.setMinimumHeight(190)
        self.courses_list.itemChanged.connect(self.refresh_course_hint)
        self.courses_list.itemChanged.connect(self.invalidate_preview)
        course_layout.addWidget(self.courses_list)
        row = QHBoxLayout()
        self.new_course = QLineEdit()
        self.new_course.setPlaceholderText("输入新课程名称")
        self.new_course.returnPressed.connect(self.add_course)
        row.addWidget(self.new_course, 1)
        row.addWidget(self._button("添加", self.add_course))
        course_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self._button("修改选中课程", self.edit_course))
        row.addWidget(self._button("删除选中课程", self.delete_course))
        row.addStretch()
        course_layout.addLayout(row)
        columns.addWidget(course_card, 1)
        layout.addLayout(columns, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._button("下一步：生成目录  →", lambda: self.tabs.setCurrentIndex(1), True))
        layout.addLayout(row)
        layout.addStretch()
        return scroll

    def choose_image(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择课表图片", "", "图片 (*.png *.jpg *.jpeg)")
        if selected:
            self.set_image(Path(selected))

    def set_image(self, path: Path):
        if not path.is_file() or path.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            self.ocr_status.setText("只接受一张存在的 PNG / JPG / JPEG 图片；原图片和课程保留。")
            return False
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.ocr_status.setText("图片无法解码；原图片和课程保留。")
            return False
        if self.image_path != path and self.courses_list.count() and QMessageBox.question(
                self, "替换课表图片", "已有课程列表。换图后原列表仍保留，开始重新识别时会清空。继续换图？", defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return False
        self.image_path = path
        self.image_label.setText(str(path))
        self.thumbnail.setPixmap(pixmap.scaled(560, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        self.ocr_status.setText("图片已选择，点击“开始本地识别”。")
        self.ocr_button.setEnabled(True)
        return True

    def start_ocr(self):
        if not self.image_path or not self.image_path.is_file():
            self.ocr_status.setText("请先选择存在的课表图片。")
            return
        if self.courses_list.count() and QMessageBox.question(
                self, "重新识别", "重新识别将替换已核对或手工修改的课程列表，继续？", defaultButton=QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.ocr_button.setEnabled(False)
        self.ocr_progress.setVisible(False)
        self.cancel_ocr_button.setVisible(True)
        self.ocr_status.setText("正在本机识别课表，请稍候…")
        self.worker = OcrWorker(self.image_path)
        self.worker.stage.connect(self.ocr_status.setText)
        self.worker.completed.connect(self.ocr_finished)
        self.worker.failed.connect(self.ocr_failed)
        self.worker.finished.connect(self.ocr_stopped)
        self.worker.start()

    def ocr_stopped(self):
        self.ocr_button.setEnabled(True)
        self.ocr_progress.setVisible(False)
        self.cancel_ocr_button.setVisible(False)

    def cancel_ocr(self):
        if self.worker:
            self.worker.request_cancel()

    def start_prewarm(self):
        def warm():
            if getattr(self, "_closing", False) or (self.worker and self.worker.isRunning()):
                return
            self.prewarm_worker = OcrWorker(None)
            self.prewarm_worker.failed.connect(lambda error: log.warning("ocr_prewarm_failed %s", error))
            self.prewarm_worker.start()
        QTimer.singleShot(400, warm)

    def ocr_finished(self, lines: list[str]):
        candidates = extract_candidates(lines)
        self.courses_list.clear()
        for name in candidates:
            self._add_course_item(name)
        self.refresh_course_hint()
        if candidates:
            self.ocr_status.setText(f"识别完成：得到 {len(candidates)} 门候选课程。请核对名称后生成目录。")
        else:
            self.ocr_status.setText("识别完成，但未找到课程名称。可手动添加，或换一张清晰课表。")

    def ocr_failed(self, error: str):
        self.ocr_status.setText("本地 OCR 失败：" + error + "。仍可手动添加课程。")

    def _add_course_item(self, name: str):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.courses_list.addItem(item)
        self.refresh_course_hint()
        self.invalidate_preview()

    def refresh_course_hint(self, *_):
        count = len([name for name in self.course_names() if name.strip()])
        self.course_hint.setText(f"{count} 门课程")

    def add_course(self):
        name = self.new_course.text().strip()
        if name:
            self._add_course_item(name)
            self.new_course.clear()
            self.refresh_course_hint()

    def edit_course(self):
        item = self.courses_list.currentItem()
        if item:
            self.courses_list.editItem(item)

    def delete_course(self):
        row = self.courses_list.currentRow()
        if row >= 0:
            self.courses_list.takeItem(row)
            self.refresh_course_hint()
            self.invalidate_preview()

    def course_names(self) -> list[str]:
        return [self.courses_list.item(i).text() for i in range(self.courses_list.count())]

