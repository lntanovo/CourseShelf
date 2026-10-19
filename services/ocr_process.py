"""One local OCR process caches its model; cancellation discards the process."""
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from file_ops import Cancelled

_process = None
_lock = threading.Lock()


def stop():
    global _process
    process, _process = _process, None
    if process is not None:
        if process.poll() is None:
            process.terminate()
        process.wait()
        if process.stdin:
            process.stdin.close()


def recognize(image, cancelled, stage):
    global _process
    with _lock, tempfile.TemporaryDirectory(prefix="courseshelf-ocr-") as temporary:
        if cancelled():
            raise Cancelled("识别已取消")
        if _process is None or _process.poll() is not None:
            stop()
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve().parents[1] / "app.py"))
            command.append("--ocr-service")
            _process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = Path(temporary) / "result.json"
        status = Path(temporary) / "stage.txt"
        assert _process.stdin is not None
        _process.stdin.write(json.dumps({"image": str(image) if image else None,
                                        "output": str(output), "stage": str(status)}, ensure_ascii=False) + "\n")
        _process.stdin.flush()
        previous = ""
        try:
            while not output.exists():
                if cancelled():
                    raise Cancelled("识别已取消，原课程列表保留")
                if _process.poll() is not None:
                    raise RuntimeError("OCR 进程已意外退出")
                if status.exists():
                    current = status.read_text(encoding="utf-8")
                    if current != previous:
                        stage(current)
                        previous = current
                threading.Event().wait(0.04)
            result = json.loads(output.read_text(encoding="utf-8"))
            if status.exists():
                stage(status.read_text(encoding="utf-8"))
            if "error" in result:
                raise RuntimeError(result["error"])
            if cancelled():
                raise Cancelled("识别已取消，原课程列表保留")
            return result.get("lines", [])
        except BaseException:
            stop()
            raise


def service_main():
    from organizer import local_ocr, ocr_engine
    stream = sys.stdin
    if stream is None and os.name == "nt":
        import ctypes
        import msvcrt
        get_handle = ctypes.windll.kernel32.GetStdHandle
        get_handle.restype = ctypes.c_void_p
        stream = os.fdopen(msvcrt.open_osfhandle(get_handle(-10), os.O_RDONLY), "r", encoding="utf-8")
    if stream is None:
        raise RuntimeError("OCR 本地进程输入管道不可用")
    stream.reconfigure(encoding="utf-8")
    for line in stream:
        request = json.loads(line)
        status = Path(request["stage"])
        try:
            if request["image"]:
                lines = local_ocr(Path(request["image"]), stage=lambda text: status.write_text(text, encoding="utf-8"))
            else:
                status.write_text("正在预热本地模型…", encoding="utf-8")
                ocr_engine()
                lines = []
            result = {"lines": lines}
        except Exception as exc:
            result = {"error": str(exc)}
        output = Path(request["output"])
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(output)
