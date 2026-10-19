"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
)

from organizer import save_root
from runtime import (log,
                     open_with_shell)
from dialogs import confirm



class RootMixin:
    def root_path(self) -> Path | None:
        from services.browser import local_path
        raw = self.root_edit.text().strip()
        path = Path(raw) if raw else None
        return path if path is not None and local_path(path) and not path.is_symlink() and not path.is_junction() and path.is_dir() else None

    def choose_root(self):
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.undo_worker, self.file_action_worker)):
            self.statusBar().showMessage("请等待归档结束或先取消批次")
            return
        initial = self.root_edit.text() if self.root_path() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择现有资料总目录", initial)
        if selected:
            self.root_edit.setText(selected)
            self.root_changed()

    def root_changed(self, *, save: bool = True, preferred: str | None = None):
        root = self.root_path()
        if root is None:
            self.root_status.setText("资料目录不存在或未选择。请选一个已有的本机文件夹；不会自动创建。")
            self.current_directory = None
            self.browser_path_label.setText("没有可浏览的资料目录")
            self.files_table.setRowCount(0)
            self.files_title.setText("文件 · 0 个")
            self.folder_tree.clear()
            self.tree_items.clear()
            self.refresh_targets()
            self.missing_label.setText("资料总目录失效；请重新选择。不会自动创建目录。")
            self.missing_combo.clear()
            return
        root = root.resolve()
        log.info("root_changed root=%s", root)
        if self.root_edit.text() != str(root):
            self.root_edit.setText(str(root))
        if save:
            try:
                save_root(root)
            except OSError as exc:
                self.root_status.setText("目录可用，但设置保存失败：" + str(exc))
        self.root_edit.setToolTip(str(root))
        self.root_status.setText("本机资料库 · 默认复制，原文件保留")
        self.refresh_browser(preferred=preferred or str(root), remember=save)

    def show_about(self):
        QMessageBox.information(self, "关于 CourseShelf", "完全本地的课表识别和课程资料整理工具。\n默认复制资料；移动和删除都需要明确选择。\n资料保存在窗口顶部显示的资料总目录。")

    def open_root(self):
        root = self.root_path()
        if root is None:
            self.root_status.setText("无法打开：资料总目录不存在，请重新选择。")
            return
        open_with_shell(root, self.statusBar().showMessage)

    def closeEvent(self, event):
        self._scan_pending = False
        prewarm = getattr(self, "prewarm_worker", None)
        if prewarm and prewarm.isRunning():
            prewarm.request_cancel()
            prewarm.wait(1000)
        for worker in getattr(self, "_directory_workers", []):
            if worker.isRunning():
                worker.request_cancel()
                worker.wait(1000)
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.request_cancel()
            self.scan_worker.wait(1000)
        business = [worker for worker in (self.worker, self.file_worker, self.undo_worker, self.file_action_worker)
                    if worker is not None and worker.isRunning()]
        workers = [worker for worker in (self.worker, self.file_worker, self.scan_worker, self.undo_worker, self.file_action_worker, prewarm,
                                         *getattr(self, "_directory_workers", []))
                   if worker is not None and worker.isRunning()]
        if workers:
            if business and not getattr(self, "_closing", False) and not confirm(self, "退出 CourseShelf", "取消后台任务并退出？已完成的文件会保留。", "取消任务并退出"):
                event.ignore()
                return
            for worker in workers:
                worker.cancel_requested = True
            self._closing = True
            for worker in workers:
                worker.finished.connect(self.close)
            event.ignore()
            return
        self._closing = True
        self.flush_view_settings()
        if hasattr(self, "appearance_timer") and self.appearance_timer.isActive():
            self.save_appearance()
        from services.ocr_process import stop
        stop()
        super().closeEvent(event)

