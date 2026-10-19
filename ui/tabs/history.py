"""Desktop UI for the local timetable and file organizer."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from runtime import (log)
from dialogs import confirm
from tasks import UndoWorker



class HistoryMixin:
    def _make_history_tab(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        note = QLabel("复制撤销将已校验的目标送入回收站；移动撤销将文件移回原路径。目标有改动或原路径被占用时拒绝撤销。分类回收站操作请手动还原。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.history_all = QCheckBox("显示全部本机资料目录的历史")
        self.history_all.toggled.connect(self.refresh_history)
        layout.addWidget(self.history_all)
        self.history_tree = QTreeWidget()
        self.history_tree.setHeaderLabels(["批次 / 时间", "操作", "来源", "目标", "结果"])
        layout.addWidget(self.history_tree)
        actions = QHBoxLayout()
        actions.addWidget(self._button("刷新记录", self.refresh_history))
        self.undo_button = self._button("撤销选中操作", self.undo_selected)
        actions.addWidget(self.undo_button)
        layout.addLayout(actions)
        self.history_status = QLabel("历史保存在本机 AppData，不随资料目录搬到其他机器。")
        self.history_status.setWordWrap(True)
        layout.addWidget(self.history_status)
        return body

    def refresh_history(self):
        from history import operations
        self.history_tree.clear()
        root = self.root_path()
        if root is None and not self.history_all.isChecked():
            return
        try:
            groups = {}
            for record in operations(None if self.history_all.isChecked() else root):
                key = record["batch_id"]
                if key not in groups:
                    group = QTreeWidgetItem([key[:12]])
                    self.history_tree.addTopLevelItem(group)
                    group.setToolTip(0, record["library"])
                    groups[key] = group
                child = QTreeWidgetItem([datetime.fromtimestamp(record["ts"] / 1e9).strftime("%m-%d %H:%M:%S"),
                                         record["kind"], record["src"] or "", record["dst"] or "",
                                         record["result"] + (" · " + record["error"] if record["error"] else "")])
                child.setData(0, Qt.ItemDataRole.UserRole, record["id"])
                child.setData(0, Qt.ItemDataRole.UserRole + 1, record["library"])
                groups[key].addChild(child)
            for group in groups.values():
                group.setExpanded(True)
        except Exception as exc:
            log.exception("history_read_failed")
            self.history_status.setText("操作历史不可用；未重置历史数据库：" + str(exc))

    def undo_selected(self):
        if any(worker and worker.isRunning() for worker in (self.file_worker, self.file_action_worker)):
            self.history_status.setText("请先等待归档结束或取消批次")
            return
        current = self.history_tree.currentItem()
        operation_id = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not operation_id or self.root_path() is None:
            self.history_status.setText("请展开批次并选择一条操作")
            return
        if current.data(0, Qt.ItemDataRole.UserRole + 1) != str(self.root_path().resolve()):
            self.history_status.setText("该记录属于另一资料路径；历史保留，不能在当前目录撤销")
            return
        if self.undo_worker and self.undo_worker.isRunning():
            return
        if not confirm(self, "撤销归档", "撤销选中操作？复制的目标将移至回收站，移动的目标将移回来源。", "校验并撤销"):
            return
        self.undo_button.setEnabled(False)
        self.undo_worker = UndoWorker(self.root_path(), operation_id)
        self.undo_worker.completed.connect(self.history_status.setText)
        self.undo_worker.failed.connect(self.history_status.setText)
        self.undo_worker.finished.connect(lambda: self.undo_button.setEnabled(True))
        self.undo_worker.finished.connect(self.refresh_browser)
        self.undo_worker.start()

