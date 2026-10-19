"""Local appearance preferences, independent of library/view settings."""
import json
import os
import tempfile
from pathlib import Path

from organizer import settings_path

THEME_IDS = ("paper", "sage", "mist", "ink")


def normalize(data):
    if not isinstance(data, dict):
        data = {}
    visibility = data.get("visibility", 35)
    return {
        "theme": data.get("theme") if data.get("theme") in THEME_IDS else "paper",
        "background": data.get("background") if isinstance(data.get("background"), str) else "",
        "visibility": max(0, min(80, visibility)) if type(visibility) is int else 35,
    }


def load_preferences():
    try:
        return normalize(json.loads((settings_path().parent / "appearance.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return normalize({})


def save_preferences(data):
    path = settings_path().parent / "appearance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="appearance-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(normalize(data), stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
