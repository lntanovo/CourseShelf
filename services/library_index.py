"""Rebuildable SQLite filename cache. Disk is always authoritative."""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from file_ops import Cancelled
from inbox import linked
from organizer import settings_path


def index_path():
    return settings_path().parent / "index.db"


def connect_index():
    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if linked(path):
        raise ValueError("索引文件不能是符号链接或目录联接")
    connection = None
    initialize = False
    try:
        connection = sqlite3.connect(path, timeout=10)
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("索引校验失败")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1}:
            raise sqlite3.DatabaseError("索引版本不匹配")
        initialize = version == 0
        if not initialize:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(file_record)")}
            if not {"library", "rel_path", "name", "size", "mtime_ns", "sha256", "status", "seen_at", "course", "category"} <= columns:
                raise sqlite3.DatabaseError("索引表结构不完整")
    except sqlite3.DatabaseError:
        if connection is not None:
            connection.close()
        path.rename(path.with_name("index.broken-" + uuid.uuid4().hex + ".db"))
        connection = sqlite3.connect(path, timeout=10)
        initialize = True
    connection.row_factory = sqlite3.Row
    if initialize:
        connection.executescript("""
        PRAGMA user_version = 1;
        CREATE TABLE IF NOT EXISTS file_record (
          id INTEGER PRIMARY KEY, library TEXT NOT NULL, rel_path TEXT NOT NULL,
          name TEXT NOT NULL, ext TEXT, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
          sha256 TEXT, course TEXT, category TEXT, status TEXT NOT NULL DEFAULT 'ok',
          seen_at INTEGER NOT NULL, UNIQUE(library, rel_path));
        CREATE INDEX IF NOT EXISTS file_record_name ON file_record(name);
        CREATE INDEX IF NOT EXISTS file_record_course ON file_record(library, course, category);
        """)
    return connection


def scan(root, cancelled=lambda: False, progress=lambda value: None):
    root = Path(root)
    if linked(root) or not root.is_dir():
        raise ValueError("资料总目录不可扫描")
    library = str(root.resolve())
    seen, count = time.time_ns(), 0

    def walk_error(error):
        raise error

    with closing(connect_index()) as connection, connection:
        try:
            for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
                if cancelled():
                    raise Cancelled("扫描已取消")
                dirs[:] = [name for name in dirs if not linked(Path(parent) / name)]
                for name in files:
                    if cancelled():
                        raise Cancelled("扫描已取消")
                    path = Path(parent) / name
                    if name.startswith(".courseshelf") or linked(path):
                        continue
                    try:
                        stat = path.stat()
                    except FileNotFoundError:
                        continue
                    relative = path.relative_to(root)
                    parts = relative.parts
                    course = parts[1] if len(parts) >= 3 else ""
                    category = parts[2] if len(parts) >= 4 else ""
                    connection.execute("""
                      INSERT INTO file_record(library,rel_path,name,ext,size,mtime_ns,course,category,seen_at)
                      VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(library,rel_path) DO UPDATE SET
                      name=excluded.name, ext=excluded.ext,
                      sha256=CASE WHEN size=excluded.size AND mtime_ns=excluded.mtime_ns THEN sha256 ELSE NULL END,
                      size=excluded.size,mtime_ns=excluded.mtime_ns,course=excluded.course,
                      category=excluded.category,seen_at=excluded.seen_at,status='ok'
                    """, (library, relative.as_posix(), name, path.suffix.casefold(), stat.st_size,
                          stat.st_mtime_ns, course, category, seen))
                    count += 1
                    if count % 100 == 0:
                        progress(count)
            connection.execute("UPDATE file_record SET status='missing' WHERE library=? AND seen_at<>?", (library, seen))
        except BaseException:
            connection.rollback()
            raise
    return count


def search(root, text="", course="", category="", limit=500):
    # LIKE is deliberately portable; no FTS extension or tokenizer is required.
    def pattern(value):
        return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    connection = connect_index()
    try:
        rows = connection.execute(r"""SELECT * FROM file_record WHERE library=? AND status='ok'
          AND name LIKE ? ESCAPE '\' AND course LIKE ? ESCAPE '\' AND category LIKE ? ESCAPE '\'
          ORDER BY name COLLATE NOCASE LIMIT ?""",
                                  (str(Path(root).resolve()), pattern(text), pattern(course), pattern(category), limit)).fetchall()
        # A stale cache must never make an externally removed file appear openable.
        return [dict(row) for row in rows if (Path(root) / row["rel_path"]).is_file()
                and not linked(Path(root) / row["rel_path"])]
    finally:
        connection.close()
