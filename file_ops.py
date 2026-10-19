"""Streaming copy/move with a private partial file and no overwrite."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Callable

log = logging.getLogger("courseshelf")


class Cancelled(Exception):
    pass


class PartialMoveError(OSError):
    def __init__(self, target: Path, cause: Exception):
        self.target = target
        super().__init__(f"复制成功、移动未完成。目标：{target}；来源删除失败，两个文件均保留：{cause}")


def _sha256(path: Path, cancelled: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if cancelled and cancelled():
                raise Cancelled("操作已取消；来源文件保持不变")
            digest.update(block)
    return digest.hexdigest()


def transfer(
    source: Path, destination_dir: Path, *, root: Path, mode: str = "copy",
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    source, destination_dir, root = map(Path, (source, destination_dir, root))
    log.info("transfer_start src=%s dst=%s mode=%s", source, destination_dir, mode)
    if mode not in {"copy", "move"}:
        raise ValueError("操作方式只能是复制或移动")
    if not source.is_file() or source.is_symlink():
        raise ValueError("来源必须是存在的普通文件，不能是符号链接")
    if not root.is_dir() or root.is_symlink() or not destination_dir.is_dir() or destination_dir.is_symlink():
        raise ValueError("资料总目录或目标分类目录不存在")
    if not destination_dir.resolve().is_relative_to(root.resolve()):
        raise ValueError("目标分类不在资料总目录内")
    if source.resolve().parent == destination_dir.resolve() and mode == "move":
        raise ValueError("来源已经在目标目录内，无需移动")
    initial = source.stat()
    temporary = destination_dir / (".courseshelf-partial-" + uuid.uuid4().hex)
    digest = hashlib.sha256()
    committed = False
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            written = 0
            while True:
                if cancelled and cancelled():
                    raise Cancelled("操作已取消；来源文件保持不变")
                block = src.read(1024 * 1024)
                if not block:
                    break
                dst.write(block)
                digest.update(block)
                written += len(block)
                if progress:
                    progress(min(99, int(written * 100 / max(initial.st_size, 1))))
            dst.flush()
            os.fsync(dst.fileno())
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
            raise OSError("复制期间来源文件发生变化")
        if temporary.stat().st_size != initial.st_size or _sha256(temporary, cancelled) != digest.hexdigest():
            raise OSError("目标大小或 SHA-256 校验失败")
        if cancelled and cancelled():
            raise Cancelled("操作已取消；来源文件保持不变")
        log.info("transfer_verified src=%s size=%s sha256=%s", source, initial.st_size, digest.hexdigest())
        number = 0
        while True:
            filename = source.name if number == 0 else f"{source.stem} ({number}){source.suffix}"
            target = destination_dir / filename
            try:
                # Windows rename is atomic within the destination directory and
                # refuses an existing target; it also works on FAT/exFAT volumes.
                os.rename(temporary, target)
                committed = True
                break
            except FileExistsError:
                number += 1
        if mode == "move":
            try:
                source.unlink()
            except OSError as exc:
                raise PartialMoveError(target, exc) from exc
        if progress:
            progress(100)
        log.info("transfer_complete src=%s dst=%s mode=%s", source, target, mode)
        return target
    finally:
        if not committed:
            temporary.unlink(missing_ok=True)
