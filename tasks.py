"""Cooperative workers share cancellation and per-item result semantics."""
from __future__ import annotations

import sys
import uuid
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from catalog import writable_catalog
from file_ops import Cancelled, PartialMoveError, _sha256, transfer
from inbox import linked
from runtime import log, report_exception


class TaskWorker(QThread):
    progress = Signal(int)
    failed = Signal(str)
    item_done = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True


class FileWorker(TaskWorker):
    completed = Signal(str)

    def __init__(self, source, destination, root, mode):
        super().__init__()
        self.source, self.destination, self.root, self.mode = source, destination, root, mode

    def run(self):
        try:
            self.completed.emit(str(transfer(self.source, self.destination, root=self.root, mode=self.mode,
                                            progress=self.progress.emit, cancelled=lambda: self.cancel_requested)))
        except (OSError, ValueError, Cancelled) as exc:
            log.exception("file_failed source=%s", self.source)
            self.failed.emit(str(exc))
        except Exception as exc:
            report_exception(*sys.exc_info())
            self.failed.emit(str(exc))


class BatchWorker(TaskWorker):
    completed = Signal(object)

    def __init__(self, items, root, *, conflict="keep", indices=None):
        super().__init__()
        self.items, self.root, self.conflict = deepcopy(items), Path(root), conflict
        self.indices = list(range(len(items))) if indices is None else list(indices)
        self.batch_id = uuid.uuid4().hex
        self.mode = "move" if self.indices and all(items[i].mode == "move" for i in self.indices) else "copy"

    def run(self):
        summary = {"ok": 0, "skipped": 0, "failed": 0}
        for offset, index in enumerate(self.indices):
            item = self.items[index]
            result = {"status": "skipped", "error": "", "target": ""}
            operation_id = None
            receipt = {}
            try:
                from history import record, update
                operation_id = record(self.root, item.mode, batch_id=self.batch_id, src=item.source, result="pending")
                if self.cancel_requested:
                    raise Cancelled("批次已取消；未处理项来源保持不变")
                writable_catalog(self.root)
                if not item.course or not item.category:
                    raise Cancelled("需手选课程和分类，未写入")
                relative = Path(item.course) / item.category
                if relative.is_absolute() or len(Path(item.course).parts) != 2 or len(Path(item.category).parts) != 1 or ".." in relative.parts:
                    raise ValueError("目标路径无效")
                destination = self.root / relative
                if any(linked(parent) for parent in [destination, *destination.parents] if parent.is_relative_to(self.root)):
                    raise ValueError("目标不能经过符号链接或目录联接")
                if item.mode == "move" and item.source.resolve().is_relative_to(self.root.resolve()):
                    raise ValueError("资料总目录内的原有文件不能作为移动来源；请选择复制")
                if self.conflict == "skip" and (destination / item.source.name).exists():
                    raise Cancelled("同名目标已存在，按策略跳过")
                same_name = destination / item.source.name
                if same_name.is_file() and not linked(same_name) and item.source.is_file():
                    if same_name.stat().st_size == item.source.stat().st_size and _sha256(same_name, lambda: self.cancel_requested) == _sha256(item.source, lambda: self.cancel_requested):
                        raise Cancelled("该文件已存在于 " + str(same_name) + "；同名同内容，默认跳过")
                target = transfer(item.source, destination, root=self.root, mode=item.mode,
                                  cancelled=lambda: self.cancel_requested,
                                  receipt=receipt,
                                  on_commit=lambda path, checksum, size: update(operation_id, dst=path, sha256=checksum, size=size,
                                                                               result="ok" if item.mode == "copy" else "partial"),
                                  progress=lambda p: self.progress.emit(int((offset + p / 100) * 100 / max(len(self.indices), 1))))
                result.update(status="ok", target=str(target))
            except Cancelled as exc:
                result["error"] = str(exc)
            except PartialMoveError as exc:
                result.update(status="failed", target=str(exc.target), error=str(exc))
            except Exception as exc:
                log.exception("batch_item_failed batch=%s source=%s", self.batch_id, item.source)
                if not isinstance(exc, (OSError, ValueError)):
                    report_exception(*sys.exc_info())
                result.update(status="failed", error=str(exc))
            if operation_id is not None:
                try:
                    update(operation_id, dst=result["target"] or receipt.get("target"), sha256=receipt.get("sha256"),
                           size=receipt.get("size"), result="partial" if receipt and result["status"] != "ok" else result["status"], error=result["error"])
                except Exception as exc:
                    log.exception("history_update_failed operation=%s", operation_id)
                    result.update(status="failed", error="文件结果已保留；操作历史写入失败：" + str(exc), target=receipt.get("target", ""))
            summary[result["status"]] += 1
            self.item_done.emit(index, result)
        self.progress.emit(100)
        self.completed.emit(summary)


class ScanWorker(TaskWorker):
    completed = Signal(int)

    def __init__(self, root):
        super().__init__()
        self.root = Path(root)

    def run(self):
        from library_index import scan
        try:
            self.completed.emit(scan(self.root, lambda: self.cancel_requested, self.progress.emit))
        except Cancelled:
            pass
        except Exception as exc:
            log.exception("index_scan_failed root=%s", self.root)
            self.failed.emit(str(exc))


class UndoWorker(TaskWorker):
    completed = Signal(str)

    def __init__(self, root, operation_id):
        super().__init__()
        self.root, self.operation_id = root, operation_id

    def run(self):
        from history import undo
        try:
            self.completed.emit(undo(self.root, self.operation_id, lambda: self.cancel_requested))
        except Exception as exc:
            log.exception("undo_failed operation=%s", self.operation_id)
            self.failed.emit(str(exc))
