"""Persistent local history is independent of the rebuildable file cache."""
import sqlite3

from organizer import settings_path


def history_path():
    return settings_path().parent / "history.db"


def connect_history():
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("操作历史不能是符号链接")
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      PRAGMA user_version=1;
      CREATE TABLE IF NOT EXISTS operation (
        id INTEGER PRIMARY KEY, library TEXT NOT NULL, batch_id TEXT NOT NULL,
        kind TEXT NOT NULL, src TEXT, dst TEXT, sha256 TEXT, size INTEGER,
        result TEXT NOT NULL, error TEXT, ts INTEGER NOT NULL, undo_of INTEGER);
      CREATE INDEX IF NOT EXISTS operation_ts ON operation(ts DESC);
    """)
    return connection
