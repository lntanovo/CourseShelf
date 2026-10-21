"""A read-only activity list with local times and human-readable operations."""
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from history import read_operations
from runtime import log
from ui.widgets import StatusLabel


KINDS = {"mkdir": "创建目录", "copy": "复制", "move": "移动", "rename": "重命名",
         "trash": "移至回收站", "undo": "旧版撤销"}
RESULTS = {"ok": "成功", "pending": "进行中", "skipped": "已跳过", "failed": "失败", "partial": "部分完成"}


def operation_content(record, root):
    def display(raw):
        if not raw:
            return ""
        path = Path(raw)
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name
    source, target = display(record["src"]), display(record["dst"])
    return f"{source} → {target}" if source and target else target or source or "—"


class HistoryMixin:
    def _make_history_tab(self):
        card, layout = self._card("最近操作")
        row = QHBoxLayout()
        self.history_count = QLabel("0 条")
        row.addWidget(self.history_count)
        row.addStretch()
        row.addWidget(self._button("刷新", self.refresh_history))
        layout.addLayout(row)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["时间", "操作", "内容", "结果"])
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.setWordWrap(False)
        self.history_table.verticalHeader().hide()
        self.history_table.verticalHeader().setDefaultSectionSize(36)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 170), (1, 105), (3, 100)):
            self.history_table.setColumnWidth(column, width)
        layout.addWidget(self.history_table, 1)
        self.history_status = StatusLabel()
        self.history_status.setWordWrap(True)
        layout.addWidget(self.history_status)
        return card

    def refresh_history(self, *_):
        self.history_table.setRowCount(0)
        self.history_count.setText("0 条")
        self.history_status.clear()
        root = self.root_path()
        if root is None:
            self.history_status.setText("请选择资料库")
            return
        try:
            records = read_operations(root)
            self.history_table.setRowCount(len(records))
            for row, record in enumerate(records):
                values = (datetime.fromtimestamp(record["ts"] / 1e9).strftime("%Y-%m-%d %H:%M:%S"),
                          KINDS.get(record["kind"], "其他操作"), operation_content(record, root),
                          RESULTS.get(record["result"], "其他"))
                detail = "\n".join(str(value) for value in (record["src"], record["dst"], record["error"]) if value)
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(detail)
                    self.history_table.setItem(row, column, item)
            self.history_count.setText(f"最近 {len(records)} 条")
            if not records:
                self.history_status.setText("暂无操作记录")
        except Exception as exc:
            log.exception("history_display_failed")
            self.history_table.setRowCount(0)
            self.history_status.setText("无法读取操作记录：" + str(exc))
