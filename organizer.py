"""Local file operations and timetable OCR for the desktop demo."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

CATEGORIES = ("课件", "作业", "复习资料", "其他")
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
NOISE = re.compile(
    r"^(?:周[一二三四五六日天]|星期[一二三四五六日天]|第?\d{1,2}节|"
    r"\d{1,2}[:：]\d{2}|\d{1,2}(?:[-~—]\d{1,2})?周|"
    r"课程表|课表|时间|节次|午休|上午|下午|晚上|教室|教师|学期)$"
)


def settings_path() -> Path:
    base = Path(os.environ.get("FILES_ORGANIZER_CONFIG_DIR") or
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FilesOrganizerDemo")
    return base / "settings.json"


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_root(root: Path) -> None:
    current = load_settings()
    viewed = current.get("last_viewed") if current.get("root") == str(root) else str(root)
    save_settings(root, Path(viewed))


def save_settings(root: Path, last_viewed: Path) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"root": str(root), "last_viewed": str(last_viewed)},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_name(value: str) -> str:
    name = INVALID_CHARS.sub("_", value.strip()).rstrip(" .")
    if RESERVED.match(name):
        name = "_" + name
    if not name or name in {".", ".."}:
        raise ValueError("名称清洗后为空，请修改名称")
    return name


def build_plan(root: Path, semester: str, courses: list[str]) -> tuple[Path, list[tuple[str, Path]]]:
    if str(root) in {"", "."}:
        raise ValueError("请先选择资料总目录")
    if not root.is_dir():
        raise ValueError("资料总目录不存在，请重新选择现有目录")
    semester_name = safe_name(semester)
    seen_original: set[str] = set()
    seen_paths: dict[str, str] = {}
    items: list[tuple[str, Path]] = []
    for value in courses:
        original = value.strip()
        if not original:
            continue
        if original.casefold() in seen_original:
            continue
        seen_original.add(original.casefold())
        cleaned = safe_name(original)
        key = cleaned.casefold()
        if key in seen_paths:
            raise ValueError(f"课程“{seen_paths[key]}”和“{original}”清洗后同名（{cleaned}），请修改其中一个")
        seen_paths[key] = original
        items.append((original, root / semester_name / cleaned))
    if not items:
        raise ValueError("请至少添加一门课程")
    return root / semester_name, items


def preview_paths(root: Path, semester: str, courses: list[str]) -> list[Path]:
    semester_path, items = build_plan(root, semester, courses)
    return [semester_path, *(path for _, course in items for path in (course, *(course / c for c in CATEGORIES)))]


def create_directories(root: Path, semester: str, courses: list[str]) -> tuple[int, int, list[str]]:
    paths = preview_paths(root, semester, courses)
    created = existing = 0
    failures: list[str] = []
    for path in paths:
        try:
            if path.exists():
                if not path.is_dir():
                    raise NotADirectoryError("同名文件阻挡目录")
                existing += 1
            else:
                path.mkdir(parents=True, exist_ok=True)
                created += 1
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    return created, existing, failures


def planned_copy_path(source: Path, destination_dir: Path) -> Path:
    """Show the likely final name before copying; copy_unique still reserves it atomically."""
    stem, suffix = source.stem, source.suffix
    number = 0
    while True:
        filename = source.name if number == 0 else f"{stem} ({number}){suffix}"
        destination = destination_dir / filename
        if not destination.exists():
            return destination
        number += 1


def copy_unique(source: Path, destination_dir: Path) -> Path:
    if not source.is_file() or source.is_symlink():
        raise ValueError("请选择一个存在的普通文件")
    if not destination_dir.is_dir():
        raise ValueError("目标分类目录不存在，请先生成目录")
    stem, suffix = source.stem, source.suffix
    number = 0
    while True:
        filename = source.name if number == 0 else f"{stem} ({number}){suffix}"
        destination = destination_dir / filename
        try:
            with source.open("rb") as src, destination.open("xb") as dst:
                try:
                    shutil.copyfileobj(src, dst)
                except BaseException:
                    destination.unlink(missing_ok=True)
                    raise
            return destination
        except FileExistsError:
            number += 1


def extract_candidates(lines: list[str]) -> list[str]:
    """Conservative OCR text filter. The user confirms all candidates in the UI."""
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = re.sub(r"\s+", " ", raw).strip(" ,，;；|｜")
        text = re.sub(r"^(?:周[一二三四五六日天]|星期[一二三四五六日天])\s*", "", text)
        text = re.sub(r"(?:第?\d{1,2}(?:[-~—]\d{1,2})?周|\d{1,2}[:：]\d{2}).*$", "", text).strip()
        if (len(text) < 2 or len(text) > 35 or NOISE.match(text)
                or not re.search(r"[\u4e00-\u9fffA-Za-z]", text)):
            continue
        if text.casefold() not in seen:
            seen.add(text.casefold())
            candidates.append(text)
    return candidates


def _table_course_lines(boxes, texts) -> list[str]:
    """Read the course-name column when OCR detects a summary table header."""
    entries = []
    for box, value in zip(boxes, texts):
        x = (min(point[0] for point in box) + max(point[0] for point in box)) / 2
        y = (min(point[1] for point in box) + max(point[1] for point in box)) / 2
        entries.append((x, y, value.strip()))
    headers = [entry for entry in entries if entry[2] == "课程名称"]
    if not headers:
        return []
    header_x, header_y, _ = headers[-1]
    left_headers = [x for x, y, value in entries if value == "课程代码" and abs(y - header_y) < 25 and x < header_x]
    right_headers = [x for x, y, value in entries if value == "课程类别" and abs(y - header_y) < 25 and x > header_x]
    if not left_headers or not right_headers:
        return []
    left = (left_headers[-1] + header_x) / 2
    right = (header_x + right_headers[0]) / 2
    rows = sorted((y, int(value)) for x, y, value in entries
                  if y > header_y + 12 and x < left_headers[-1] - 30
                  and value.isdigit() and 1 <= int(value) <= 99)
    if not rows:
        return []
    result = []
    for index, (row_y, _) in enumerate(rows):
        lower = (rows[index - 1][0] + row_y) / 2 if index else header_y + 12
        upper = (row_y + rows[index + 1][0]) / 2 if index + 1 < len(rows) else row_y + 25
        fragments = sorted(((y, x, value) for x, y, value in entries
                            if left < x < right and lower < y < upper), key=lambda part: (part[0], part[1]))
        if fragments:
            result.append("".join(value for _, _, value in fragments))
    return result


def local_ocr(image: Path) -> list[str]:
    """RapidOCR loads its bundled ONNX models; no network request is used."""
    if not image.is_file():
        raise FileNotFoundError(image)
    import rapidocr
    from rapidocr import RapidOCR

    model_dir = Path(rapidocr.__file__).parent / "models"
    models = {
        "Det.model_path": model_dir / "PP-OCRv6_det_small.onnx",
        "Cls.model_path": model_dir / "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "Rec.model_path": model_dir / "PP-OCRv6_rec_small.onnx",
    }
    missing = [str(path) for path in models.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少本地 OCR 模型：" + ", ".join(missing))
    result = RapidOCR(params={key: str(value) for key, value in models.items()})(str(image))
    if result.txts is None:
        return []
    if result.boxes is not None:
        table_lines = _table_course_lines(result.boxes, result.txts)
        if table_lines:
            return table_lines
    return list(result.txts)
