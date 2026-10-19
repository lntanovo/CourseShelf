from PySide6.QtCore import Signal
from file_ops import Cancelled
from runtime import log
from services.ocr_process import recognize
from .worker import TaskWorker

class OcrWorker(TaskWorker):
    completed = Signal(list)
    stage = Signal(str)

    def __init__(self, image):
        super().__init__()
        self.image = image

    def run(self):
        try:
            self.completed.emit(recognize(self.image, lambda: self.cancel_requested, self.stage.emit))
        except Cancelled as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.exception("ocr_failed image=%s", self.image)
            self.failed.emit(str(exc))
