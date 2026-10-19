"""Managed course folders; the filesystem remains the source of truth."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from send2trash import send2trash

from organizer import CATEGORIES, build_plan, safe_name

CATALOG_NAME = ".courseshelf.json"
SCHEMA_VERSION = 2
log = logging.getLogger("courseshelf")
_snapshot: ContextVar[tuple[Path, dict] | None] = ContextVar("catalog_snapshot", default=None)


def current_catalog(root):
    cached = _snapshot.get()
    if cached is not None and cached[0] == Path(root):
        return cached[1]
    return load_catalog(root)


@contextmanager
def catalog_snapshot(root):
    token = _snapshot.set((Path(root), load_catalog(root)))
    try:
        yield
    finally:
        _snapshot.reset(token)


def _audit(root, kind, *, src=None, dst=None, result="ok", error="", batch_id=None):
    from history import record
    try:
        record(root, kind, src=src, dst=dst, result=result, error=error, batch_id=batch_id)
    except Exception:
        # Never lose successful folder registrations because auxiliary history failed.
        log.exception("catalog_history_failed kind=%s src=%s dst=%s", kind, src, dst)


class CatalogError(ValueError):
    pass


def _component(value: str) -> str:
    if not isinstance(value, str) or value in {"", ".", ".."} or safe_name(value) != value:
        raise CatalogError(f"无效的目录名称：{value!r}")
    return value


def _key(semester: str, course: str) -> str:
    return _component(semester) + "/" + _component(course)


def _parts(key: str) -> tuple[str, str]:
    parts = key.split("/")
    if len(parts) != 2:
        raise CatalogError(f"管理记录含无效课程路径：{key!r}")
    return _component(parts[0]), _component(parts[1])


def _root(root: Path) -> Path:
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise CatalogError("资料总目录不存在，请重新选择")
    return root.resolve(strict=True)


def catalog_path(root: Path) -> Path:
    return _root(root) / CATALOG_NAME


def load_catalog(root: Path) -> dict:
    path = catalog_path(root)
    if path.is_symlink():
        return _read_only("管理记录不能是符号链接")
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "courses": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _read_only(f"管理记录不可读取：{exc}")
    try:
        version = data.get("schema_version") if isinstance(data, dict) else None
        if not isinstance(version, int) or version < 1:
            raise CatalogError("管理记录版本或格式不正确")
        if version > SCHEMA_VERSION:
            return _read_only("该资料目录由更新版本的 CourseShelf 创建")
        _validate(data)
        if version < SCHEMA_VERSION:
            migrated = _migrate(data, version)
            _validate(migrated)
            _atomic_save(root, migrated)
            data = migrated
        return data
    except (OSError, ValueError, TypeError) as exc:
        log.exception("catalog_read_only path=%s", path)
        return _read_only("管理记录迁移或校验失败：" + str(exc))


def _read_only(warning):
    return {"schema_version": SCHEMA_VERSION, "courses": {}, "_read_only": True,
            "_warning": warning + "；仅浏览磁盘，管理操作已禁用"}


def _migrate(data, from_version):
    # New migrations are appended here; never mutate the input before validation.
    result = json.loads(json.dumps(data))
    while from_version < SCHEMA_VERSION:
        if from_version == 1:
            for record in result["courses"].values():
                record.setdefault("aliases", [])
            from_version = 2
        else:
            raise CatalogError("没有可用的清单迁移路径")
    result["schema_version"] = from_version
    return result


def _validate(data):
    if not isinstance(data.get("courses"), dict):
        raise CatalogError("管理记录课程格式不正确")
    for key, record in data["courses"].items():
        _parts(key)
        if not isinstance(record, dict) or not isinstance(record.get("categories"), list):
            raise CatalogError(f"管理记录含无效分类：{key}")
        categories = record["categories"]
        if any(not isinstance(name, str) or _component(name) != name for name in categories):
            raise CatalogError(f"管理记录含无效分类名称：{key}")
        if len({name.casefold() for name in categories}) != len(categories):
            raise CatalogError(f"管理记录含重复分类：{key}")
        aliases = record.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 128 for alias in aliases):
            raise CatalogError(f"管理记录含无效课程别名：{key}")


def writable_catalog(root):
    data = load_catalog(root)
    if data.get("_read_only"):
        raise CatalogError(data["_warning"])
    _check_backup(root)
    return data


def _check_backup(root):
    backup = _root(root) / (CATALOG_NAME + ".bak")
    if backup.is_symlink() or backup.is_junction() or (backup.exists() and not backup.is_file()):
        raise CatalogError("管理记录备份路径被链接或目录占用；拒绝写入")


def save_catalog(root: Path, data: dict) -> None:
    writable_catalog(root)
    if data.get("_read_only"):
        raise CatalogError(data["_warning"])
    _validate(data)
    _atomic_save(root, data)


def _atomic_save(root: Path, data: dict) -> None:
    root = _root(root)
    _check_backup(root)
    path = root / CATALOG_NAME
    if path.is_file():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    fd, temporary = tempfile.mkstemp(prefix=".courseshelf-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _folder(root: Path, *parts: str, must_exist: bool = True) -> Path:
    root = _root(root)
    current = root
    for part in parts:
        current = current / _component(part)
        if current.is_symlink() or current.is_junction():
            raise CatalogError("不能管理符号链接目录：" + str(current))
    if must_exist and not current.is_dir():
        raise CatalogError("目录不存在：" + str(current))
    if not current.resolve().is_relative_to(root):
        raise CatalogError("目录不在资料总目录内")
    return current


def is_managed(root: Path, semester: str, course: str) -> bool:
    return _key(semester, course) in current_catalog(root)["courses"]


def categories_for(root: Path, semester: str, course: str) -> list[str]:
    record = current_catalog(root)["courses"].get(_key(semester, course))
    if record is not None:
        return list(record["categories"])
    existing = _folder(root, semester, course, must_exist=False)
    if existing.is_dir():
        return disk_categories(root, semester, course)
    return list(CATEGORIES)


def disk_categories(root: Path, semester: str, course: str) -> list[str]:
    folder = _folder(root, semester, course)
    return sorted((p.name for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction()), key=str.casefold)


def plan_paths(root: Path, semester: str, courses: list[str]) -> tuple[Path, list[tuple[Path, list[str]]], list[Path]]:
    semester_path, course_items = build_plan(root, semester, courses)
    paths = [semester_path]
    items = []
    for _, course_path in course_items:
        categories = categories_for(root, semester_path.name, course_path.name)
        paths.append(course_path)
        paths.extend(course_path / category for category in categories)
        items.append((course_path, categories))
    return semester_path, items, paths


def create_plan(root: Path, semester: str, courses: list[str]) -> tuple[int, int, list[str], Path]:
    data = writable_catalog(root)
    semester_path, items, paths = plan_paths(root, semester, courses)
    previously_existing = {course_path for course_path, _ in items if course_path.is_dir()}
    created = existing = 0
    batch_id = uuid.uuid4().hex
    failures = []
    for path in paths:
        try:
            if path.is_symlink() or path.is_junction():
                raise CatalogError("不能复用符号链接目录")
            if path.exists():
                if not path.is_dir():
                    raise CatalogError("同名文件阻挡目录")
                existing += 1
            else:
                path.mkdir()  # Parent must already exist in the plan.
                created += 1
                _audit(root, "mkdir", dst=path, batch_id=batch_id)
        except (OSError, CatalogError) as exc:
            failures.append(f"{path}: {exc}")
    for course_path, categories in items:
        key = _key(semester_path.name, course_path.name)
        if course_path.is_dir() and not course_path.is_symlink() and not course_path.is_junction() and (course_path not in previously_existing or key in data["courses"]):
            succeeded = [name for name in categories if (course_path / name).is_dir()
                         and not (course_path / name).is_symlink() and not (course_path / name).is_junction()]
            record = data["courses"].setdefault(key, {"categories": []})
            record["categories"].extend(name for name in succeeded if name not in record["categories"])
    save_catalog(root, data)
    log.info("create_plan root=%s created=%s existing=%s failures=%s", root, created, existing, failures)
    return created, existing, failures, semester_path


def import_course(root: Path, semester: str, course: str) -> None:
    categories = disk_categories(root, semester, course)
    data = writable_catalog(root)
    record = data["courses"].setdefault(_key(semester, course), {"categories": []})
    record["categories"] = [name for name in record["categories"] if name in categories]
    record["categories"].extend(name for name in categories if name not in record["categories"])
    save_catalog(root, data)


def set_aliases(root, semester, course, aliases):
    data = writable_catalog(root)
    record = data["courses"].get(_key(semester, course))
    if record is None:
        raise CatalogError("请先将课程目录纳入管理")
    if not isinstance(aliases, list) or any(not isinstance(value, str) or not value.strip() or len(value.strip()) > 128 for value in aliases):
        raise CatalogError("别名必须是非空文字，且每条不超过 128 字符")
    values, seen = [], set()
    for alias in aliases:
        value = alias.strip()
        if value.casefold() not in seen:
            values.append(value)
            seen.add(value.casefold())
    record["aliases"] = values
    save_catalog(root, data)


def aliases_for(root):
    return {key: list(value.get("aliases", [])) for key, value in current_catalog(root)["courses"].items()}


def _checked_category(root: Path, semester: str, course: str, category: str) -> Path:
    writable_catalog(root)
    if not is_managed(root, semester, course):
        raise CatalogError("请先将课程目录纳入管理")
    return _folder(root, semester, course, category)


def add_category(root: Path, semester: str, course: str, value: str) -> Path:
    course_path = _folder(root, semester, course)
    name = safe_name(value)
    if name != value.strip():
        raise CatalogError("分类名称含 Windows 不允许的字符，请修改")
    if any(p.name.casefold() == name.casefold() for p in course_path.iterdir()):
        raise CatalogError("同名分类或文件已存在")
    data = writable_catalog(root)
    record = data["courses"].get(_key(semester, course))
    if record is None:
        raise CatalogError("请先将课程目录纳入管理")
    destination = course_path / name
    destination.mkdir()
    _audit(root, "mkdir", dst=destination)
    record["categories"].append(name)
    save_catalog(root, data)
    return destination


def _checked_contents(root, folder, cancelled=lambda: False):
    """Directory ownership never implicitly grants ownership of its contents."""
    from file_ops import Cancelled, _sha256
    from history import owned_record
    files = []
    def fail(error):
        raise error
    for directory, dirs, names in os.walk(folder, followlinks=False, onerror=fail):
        if cancelled():
            raise Cancelled("分类操作已取消")
        for name in [*dirs, *names]:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise CatalogError("分类包含链接，拒绝整体修改：" + str(path))
        for name in names:
            path = Path(directory) / name
            item = owned_record(root, path)
            if not path.is_file() or item is None:
                raise CatalogError("分类包含非本应用归档的文件，拒绝整体修改：" + str(path))
            before = path.stat()
            digest = _sha256(path, cancelled)
            after = path.stat()
            if before.st_size != item["size"] or digest != item["sha256"] or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise CatalogError("分类包含内容已改变的文件，拒绝整体修改：" + str(path))
            files.append((path, item))
    if cancelled():
        raise Cancelled("分类操作已取消")
    return files


def rename_category(root: Path, semester: str, course: str, old: str, value: str, cancelled=lambda: False) -> Path:
    source = _checked_category(root, semester, course, old)
    name = safe_name(value)
    if name != value.strip():
        raise CatalogError("分类名称含 Windows 不允许的字符，请修改")
    if name == old:
        return source
    destination = source.parent / name
    if any(p.name.casefold() == name.casefold() and p.name.casefold() != old.casefold() for p in source.parent.iterdir()):
        raise CatalogError("目标分类或文件已存在")
    data = writable_catalog(root)
    record = data["courses"][_key(semester, course)]
    if old not in record["categories"]:
        raise CatalogError("该分类尚未纳入管理")
    files = _checked_contents(root, source, cancelled)
    if name.casefold() == old.casefold():
        temporary = source.parent / (".courseshelf-rename-" + uuid.uuid4().hex)
        source.rename(temporary)
        try:
            temporary.rename(destination)
        except OSError:
            temporary.rename(source)
            raise
    else:
        source.rename(destination)
    record["categories"][record["categories"].index(old)] = name
    save_catalog(root, data)
    _audit(root, "rename", src=source, dst=destination)
    from history import record as record_file
    for path, item in files:
        try:
            record_file(root, "rename", src=path, dst=destination / path.relative_to(source),
                        sha256=item["sha256"], size=item["size"])
        except Exception:
            log.exception("category_file_history_failed path=%s", path)
    return destination


def count_contents(folder: Path, cancelled=lambda: False) -> tuple[int, int]:
    from file_ops import Cancelled
    files = directories = 0
    for _, dirs, names in os.walk(folder, followlinks=False):
        if cancelled():
            raise Cancelled("统计已取消")
        directories += len(dirs)
        files += len(names)
    return files, directories


def trash_category(root: Path, semester: str, course: str, category: str, cancelled=lambda: False) -> None:
    path = _checked_category(root, semester, course, category)
    data = writable_catalog(root)
    record = data["courses"][_key(semester, course)]
    if category not in record["categories"]:
        raise CatalogError("该分类尚未纳入管理")
    _checked_contents(root, path, cancelled)
    send2trash(str(path))  # Never fall back to permanent recursive deletion.
    log.info("trash_category path=%s", path)
    record["categories"].remove(category)
    save_catalog(root, data)
    _audit(root, "trash", src=path)


def restore_defaults(root: Path, semester: str, course: str) -> list[Path]:
    _folder(root, semester, course)
    data = writable_catalog(root)
    record = data["courses"].get(_key(semester, course))
    if record is None:
        raise CatalogError("请先将课程目录纳入管理")
    created, failures = [], []
    for name in CATEGORIES:
        try:
            path = _folder(root, semester, course, name, must_exist=False)
            if path.exists() and not path.is_dir():
                raise CatalogError("默认分类被同名文件阻挡：" + str(path))
            if not path.exists():
                path.mkdir()
                created.append(path)
                _audit(root, "mkdir", dst=path)
            if name not in record["categories"]:
                record["categories"].append(name)
        except (OSError, ValueError) as exc:
            failures.append(str(exc))
    save_catalog(root, data)
    if failures:
        raise CatalogError("其余默认分类已登记；失败项：\n" + "\n".join(failures))
    return created


def managed_paths(root: Path) -> list[Path]:
    data = current_catalog(root)
    root = _root(root)
    result = set()
    for key, record in data["courses"].items():
        semester, course = _parts(key)
        result.add(_folder(root, semester, must_exist=False))
        result.add(_folder(root, semester, course, must_exist=False))
        for category in record["categories"]:
            result.add(_folder(root, semester, course, category, must_exist=False))
    return sorted(result, key=lambda path: (len(path.parts), str(path).casefold()))


def missing_paths(root: Path) -> list[Path]:
    return [path for path in managed_paths(root) if not path.is_dir() or path.is_symlink()]


def restore_missing(root: Path, path: Path) -> list[Path]:
    writable_catalog(root)
    root = _root(root)
    expected = set(managed_paths(root))
    path = Path(path)
    if path not in expected:
        raise CatalogError("只能重建已登记的受管目录")
    missing = []
    current = path
    while current != root:
        if current.is_symlink() or current.is_junction() or (current.exists() and not current.is_dir()):
            raise CatalogError("目录路径被文件或符号链接阻挡：" + str(current))
        if not current.exists():
            missing.append(current)
        current = current.parent
    for folder in reversed(missing):
        folder.mkdir()
        _audit(root, "mkdir", dst=folder)
    log.info("restore_missing path=%s created=%s", path, len(missing))
    return list(reversed(missing))
