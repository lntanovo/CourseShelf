"""Small snapshots are immediate; large directory enumeration runs in workers."""
import ctypes
import os
from pathlib import Path

from file_ops import Cancelled
from inbox import linked


def local_path(path):
    path = Path(path)
    if str(path).startswith(("\\\\", "//")):
        return False
    return not (os.name == "nt" and path.drive and ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4)


def library_ancestor(directory):
    """Detect a selected child folder without silently changing the library root."""
    directory = Path(directory)
    if (directory / ".courseshelf.json").is_file():
        return None
    for parent in directory.parents:
        if linked(parent):
            return None
        metadata = parent / ".courseshelf.json"
        if metadata.is_file() and not linked(metadata):
            return parent
    return None


def read_directory(root, directory, cancelled=lambda: False, limit=None):
    root, directory = Path(root), Path(directory)
    if not local_path(directory) or linked(directory) or not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("目录已失效、为网络目录或不在资料总目录内")
    folders, files = [], []
    with os.scandir(directory) as entries:
        for count, entry in enumerate(entries):
            if cancelled():
                raise Cancelled("目录扫描已取消")
            if limit is not None and count >= limit:
                return None
            path = Path(entry.path)
            if entry.is_symlink() or path.is_junction():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    folders.append(path)
                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    files.append((path, stat.st_size, stat.st_mtime))
            except FileNotFoundError:
                continue
    return {"folders": sorted(folders, key=lambda path: path.name.casefold()),
            "files": sorted(files, key=lambda row: row[0].name.casefold())}
