"""Portable CourseShelf uninstaller. Never recursively deletes directories."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MANIFEST = "release-manifest.json"


def release_dir() -> Path:
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def settings_file() -> Path:
    base = Path(os.environ.get("FILES_ORGANIZER_CONFIG_DIR") or
                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CourseShelf")
    return base / "settings.json"


def settings_files() -> list[Path]:
    paths = [settings_file()]
    if not os.environ.get("FILES_ORGANIZER_CONFIG_DIR"):
        # Explicitly clearing preferences includes the previous edition's migration source.
        paths.append(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FilesOrganizerDemo/settings.json")
    return paths


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def read_manifest(folder: Path) -> list[dict]:
    data = json.loads((folder / MANIFEST).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("files"), list):
        raise ValueError("发布清单格式错误")
    for entry in data["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise ValueError("发布清单格式错误")
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.name in {MANIFEST, "uninstall.exe"}:
            raise ValueError("发布清单包含越界或自引用文件")
    return data["files"]


def inspect(folder: Path) -> dict:
    files = read_manifest(folder)
    owned, modified, missing = [], [], []
    for entry in files:
        path = folder / entry["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            modified.append(entry["path"])
        elif not path.exists():
            missing.append(entry["path"])
        elif path.is_file() and digest(path) == entry["sha256"]:
            owned.append(entry["path"])
        else:
            modified.append(entry["path"])
    return {"owned": owned, "modified": modified, "missing": missing}


def uninstall(folder: Path, *, clear_settings: bool = False, self_cleanup: bool = False) -> dict:
    folder = folder.resolve(strict=True)
    report = inspect(folder)
    failed = []
    for rel in report["owned"]:
        path = folder / rel
        try:
            path.unlink()
        except OSError as exc:
            failed.append(f"{rel}: {exc}")
    # Only directories that held manifest-owned files are candidates. Never inspect
    # or remove unrelated empty user-created directories.
    owned_parents = set()
    for rel in report["owned"]:
        parent = (folder / rel).parent
        while parent != folder:
            owned_parents.add(parent)
            parent = parent.parent
    for directory in sorted(owned_parents, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    if clear_settings:
        for settings in settings_files():
            try:
                settings.unlink(missing_ok=True)
            except OSError as exc:
                failed.append(f"设置：{exc}")
    report["failed"] = failed
    if self_cleanup and not failed and not report["modified"]:
        _cleanup_after_exit(folder)
    return report


def _cleanup_after_exit(folder: Path) -> None:
    # Helper waits for this executable to exit before removing its own image and manifest.
    script = Path(tempfile.gettempdir()) / ("courseshelf-cleanup-" + str(os.getpid()) + ".ps1")
    script.write_text("""param([int]$TargetPid,[string]$Release,[string]$Helper)
Wait-Process -Id $TargetPid -ErrorAction SilentlyContinue
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath (Join-Path $Release 'uninstall.exe') -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath (Join-Path $Release 'uninstall.exe'))) { break }
}
Remove-Item -LiteralPath (Join-Path $Release 'release-manifest.json') -Force -ErrorAction SilentlyContinue
try { Remove-Item -LiteralPath $Release -ErrorAction Stop } catch {}
Remove-Item -LiteralPath $Helper -Force -ErrorAction SilentlyContinue
""", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                      "-TargetPid", str(os.getpid()), "-Release", str(folder), "-Helper", str(script)],
                     creationflags=flags, close_fds=True)


def _box(title: str, message: str, flags: int = 0) -> int:
    return ctypes.windll.user32.MessageBoxW(None, message, title, flags)


def app_running() -> bool:
    result = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq CourseShelf.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return any(line.strip().lower().startswith(b'"courseshelf.exe"') for line in result.stdout.splitlines())


def main() -> int:
    folder = release_dir()
    if "--report" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--report") + 1])
        output.write_text(json.dumps(inspect(folder), ensure_ascii=False), encoding="utf-8")
        return 0
    if "--execute" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--execute") + 1])
        report = uninstall(folder, clear_settings="--clear-settings" in sys.argv,
                           self_cleanup="--self-cleanup" in sys.argv)
        output.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return 0 if not report["failed"] else 1
    try:
        report = inspect(folder)
        settings = settings_file()
        while app_running():
            if _box("请先关闭 CourseShelf", "检测到 CourseShelf.exe 正在运行。请关闭应用，再点击“重试”；点击“取消”不会删除任何文件。", 0x135) != 4:
                return 0
        if _box("卸载 CourseShelf", f"便携版没有系统安装记录。\n发布文件夹：{folder}\n设置文件：{settings}\n\n删除 {len(report['owned'])} 个清单内的程序文件？\n用户资料文件夹及其中资料会保留。请先关闭 CourseShelf。", 0x124) != 6:
            return 0
        clear = _box("路径设置", "同时清除本机保存的资料目录路径设置？\n这不会删除资料。", 0x124) == 6
        result = uninstall(folder, clear_settings=clear, self_cleanup=True)
        _box("卸载结果", f"已清理 {len(result['owned']) - len(result['failed'])} 个程序文件。\n跳过改动文件 {len(result['modified'])} 个；失败 {len(result['failed'])} 个。\n用户资料未删除。")
        return 0 if not result["failed"] else 1
    except Exception as exc:
        _box("卸载失败", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
