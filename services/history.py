"""Persistent local history is independent of the rebuildable file cache."""
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from send2trash import send2trash

from catalog import writable_catalog
from file_ops import _sha256, transfer
from organizer import settings_path


def history_path():
    return settings_path().parent / "history.db"


def connect_history():
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.is_junction():
        raise ValueError("操作历史不能是符号链接")
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in {0, 1}:
        connection.close()
        raise ValueError("操作历史来自更新版本，保留原数据库并禁止修改")
    if version == 0:
        connection.executescript("""
      PRAGMA user_version=1;
      CREATE TABLE IF NOT EXISTS operation (
        id INTEGER PRIMARY KEY, library TEXT NOT NULL, batch_id TEXT NOT NULL,
        kind TEXT NOT NULL, src TEXT, dst TEXT, sha256 TEXT, size INTEGER,
        result TEXT NOT NULL, error TEXT, ts INTEGER NOT NULL, undo_of INTEGER);
      CREATE INDEX IF NOT EXISTS operation_ts ON operation(ts DESC);
        """)
    return connection


def record(root, kind, *, batch_id=None, src=None, dst=None, sha256=None, size=None,
           result="ok", error="", undo_of=None):
    with closing(connect_history()) as connection, connection:
        cursor = connection.execute("""INSERT INTO operation
          (library,batch_id,kind,src,dst,sha256,size,result,error,ts,undo_of) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                    (str(Path(root).resolve()), batch_id or uuid.uuid4().hex, kind,
                                     str(src) if src else None, str(dst) if dst else None,
                                     sha256, size, result, error, time.time_ns(), undo_of))
        return cursor.lastrowid


def update(operation_id, *, dst=None, sha256=None, size=None, result, error=""):
    with closing(connect_history()) as connection, connection:
        connection.execute("""UPDATE operation SET dst=COALESCE(?,dst),sha256=COALESCE(?,sha256),
          size=COALESCE(?,size),result=?,error=? WHERE id=?""", (str(dst) if dst else None, sha256, size, result, error, operation_id))


def operations(root, batch_id="", limit=500):
    with closing(connect_history()) as connection:
        library = str(Path(root).resolve()) if root is not None else None
        return [dict(row) for row in connection.execute("""SELECT * FROM operation WHERE (? IS NULL OR library=?)
          AND (?='' OR batch_id=?) ORDER BY ts DESC LIMIT ?""",
                                                        (library, library, batch_id, batch_id, limit))]


def owned_record(root, path):
    with closing(connect_history()) as connection:
        row = connection.execute("""SELECT * FROM operation WHERE library=? AND dst=?
          AND kind IN ('copy','move','rename') AND result='ok' AND sha256 IS NOT NULL
          ORDER BY ts DESC LIMIT 1""", (str(Path(root).resolve()), str(path))).fetchone()
        return dict(row) if row else None


def manage_file(root, path, kind, name=None, cancelled=lambda: False):
    from organizer import safe_name
    writable_catalog(root)
    root, path = Path(root).resolve(), Path(path)
    record_data = owned_record(root, path)
    if not record_data or not path.is_relative_to(root) or any(p.is_symlink() or p.is_junction() for p in [path, *path.parents]):
        raise ValueError("只能修改本应用成功归档且路径未变化的文件")
    before = path.stat()
    after_hash = _sha256(path, cancelled)
    after = path.stat()
    if before.st_size != record_data["size"] or after_hash != record_data["sha256"] or (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
        raise ValueError("文件内容已改变，拒绝修改")
    if cancelled():
        raise ValueError("操作已取消")
    target = None
    if kind == "rename":
        if not name or safe_name(name) != name or Path(name).name != name:
            raise ValueError("文件名无效")
        target = path.with_name(name)
        if target.exists():
            raise ValueError("目标同名文件已存在，拒绝覆盖")
    elif kind != "trash":
        raise ValueError("未知文件操作")
    operation_id = record(root, kind, src=path, dst=target, sha256=record_data["sha256"], size=before.st_size, result="pending")
    try:
        if kind == "rename":
            path.rename(target)
        else:
            send2trash(str(path))
        update(operation_id, result="ok")
        return "已重命名：" + str(target) if target else "已移至回收站：" + str(path)
    except Exception as exc:
        update(operation_id, result="failed", error=str(exc))
        raise


def undo(root, operation_id, cancelled=lambda: False):
    writable_catalog(root)
    root = Path(root).resolve(strict=True)
    with closing(connect_history()) as connection:
        row = connection.execute("SELECT * FROM operation WHERE id=? AND library=?", (operation_id, str(root))).fetchone()
        if row is None:
            raise ValueError("找不到本资料目录的操作记录")
        item = dict(row)
        if connection.execute("SELECT 1 FROM operation WHERE undo_of=? AND result='ok'", (operation_id,)).fetchone():
            raise ValueError("该操作已撤销")
    attempt = record(root, "undo", batch_id=item["batch_id"], src=item["dst"], dst=item["src"], result="pending", undo_of=operation_id)
    try:
        if item["kind"] == "trash":
            raise ValueError("请在 Windows 回收站中手动还原此分类")
        if item["kind"] not in {"copy", "move"} or item["result"] != "ok":
            raise ValueError("仅支持撤销成功的复制或移动记录")
        target = Path(item["dst"])
        if not target.is_relative_to(root) or any(p.is_symlink() or p.is_junction() for p in [target, *target.parents]):
            raise ValueError("目标路径已变化或越界，拒绝撤销")
        before = target.stat()
        if not item["sha256"] or before.st_size != item["size"] or _sha256(target, cancelled) != item["sha256"]:
            raise ValueError("目标内容已改变，大小或 SHA-256 不匹配，拒绝撤销")
        after = target.stat()
        if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
            raise ValueError("校验期间目标已变化，拒绝撤销")
        if cancelled():
            raise ValueError("撤销已取消")
        if item["kind"] == "copy":
            send2trash(str(target))
        else:
            source = Path(item["src"])
            if source.exists() or source.is_symlink():
                raise ValueError("来源路径已被占用，拒绝覆盖")
            if not source.parent.is_dir():
                raise ValueError("原来源目录不存在，请先恢复该目录")
            transfer(target, source.parent, root=source.parent, mode="move", target_name=source.name,
                     conflict="error", cancelled=cancelled)
        update(attempt, result="ok")
        return "撤销完成：" + str(target)
    except Exception as exc:
        update(attempt, result="failed", error=str(exc))
        raise
