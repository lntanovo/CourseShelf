"""CourseShelf executable entry point and compatible UI imports."""
import sys
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from tasks import FileWorker, OcrWorker
from organizer import local_ocr, extract_candidates
from catalog import create_plan
from file_ops import transfer
from runtime import configure_logging, install_exception_hooks, acquire_instance

def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-ocr":
        output = Path(sys.argv[3])
        try:
            lines = local_ocr(Path(sys.argv[2]))
            output.write_text(json.dumps({"courses": extract_candidates(lines), "lines": lines}, ensure_ascii=False), encoding="utf-8")
            return 0
        except Exception as exc:
            output.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            return 1
    if len(sys.argv) == 5 and sys.argv[1] == "--verify-archive":
        root, source, output = map(Path, sys.argv[2:5])
        try:
            _, _, failures, _ = create_plan(root, "打包验收", ["示例课程"])
            if failures:
                raise OSError("; ".join(failures))
            target = transfer(source, root / "打包验收" / "示例课程" / "课件", root=root, mode="copy")
            output.write_text(json.dumps({"target": str(target)}, ensure_ascii=False), encoding="utf-8")
            return 0
        except Exception as exc:
            output.write_text(json.dumps({"error": str(exc)}, ensure_ascii=False), encoding="utf-8")
            return 1
    app = QApplication(sys.argv)
    configure_logging()
    install_exception_hooks()
    instance_lock = acquire_instance()
    if instance_lock is None:
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
