"""Pure inbox preparation; suggestions never perform disk writes."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from classifier import suggest


def linked(path):
    return path.is_symlink() or path.is_junction()


@dataclass
class InboxItem:
    source: Path
    size: int = 0
    course: str | None = None
    category: str | None = None
    reason: str = "需手选"
    mode: str = "copy"
    status: str = "pending"
    error: str = ""
    target: str = ""
    suggested_course: str | None = None
    suggested_category: str | None = None


def build_inbox(paths, courses, categories, *, recursive=False, aliases=None):
    """Courses are semester/course keys; folders expand without following links."""
    expanded = []
    for raw in paths:
        path = Path(raw)
        if linked(path):
            expanded.append(path)
        elif path.is_dir():
            if recursive:
                for parent, dirs, names in os.walk(path, followlinks=False):
                    dirs[:] = sorted(name for name in dirs if not linked(Path(parent) / name))
                    expanded.extend(Path(parent) / name for name in sorted(names))
            else:
                expanded.extend(sorted((child for child in path.iterdir() if child.is_file()), key=lambda p: p.name.casefold()))
        else:
            expanded.append(path)
    seen, result = set(), []
    names = [Path(key).name for key in courses]
    for path in expanded:
        identity = os.path.normcase(os.path.abspath(path))
        if identity in seen:
            continue
        seen.add(identity)
        item = InboxItem(path)
        try:
            if linked(path) or not path.is_file():
                raise ValueError("只接受普通文件，不能是符号链接或目录联接")
            item.size = path.stat().st_size
            guess = suggest(path.name, names)
            keys = [key for key in courses if Path(key).name == guess.course]
            if len(keys) == 1:
                key = keys[0]
                guess = suggest(path.name, names, categories.get(key, []))
                item.suggested_course = key
                item.suggested_category = guess.category
            item.reason = guess.reason if len(keys) <= 1 else "跨学期课程重名，需手选"
        except (OSError, ValueError) as exc:
            item.status, item.error = "failed", str(exc)
        result.append(item)
    return result
