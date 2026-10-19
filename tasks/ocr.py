import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from PySide6.QtCore import Signal
from file_ops import Cancelled
from runtime import log
from .worker import TaskWorker

class OcrWorker(TaskWorker):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, image: Path):
        super().__init__()
        self.image = image
        self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True

    def run(self):
        try:
            # An isolated process makes an in-flight ONNX call safely cancellable.
            with tempfile.TemporaryDirectory(prefix="courseshelf-ocr-") as temporary:
                output = Path(temporary) / "result.json"
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command.append(str(Path(__file__).resolve().parents[1] / "app.py"))
                command.extend(["--verify-ocr", str(self.image), str(output)])
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    while process.poll() is None:
                        if self.cancel_requested:
                            raise Cancelled("识别已取消，原课程列表保留")
                        threading.Event().wait(0.04)
                    if self.cancel_requested:
                        raise Cancelled("识别已取消，原课程列表保留")
                    result = json.loads(output.read_text(encoding="utf-8"))
                    if process.returncode or "error" in result:
                        raise RuntimeError(result.get("error", "OCR 子进程失败"))
                    self.completed.emit(result["lines"])
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("ocr_failed image=%s", self.image)
            self.failed.emit(str(exc))

