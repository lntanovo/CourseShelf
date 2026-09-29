# CourseShelf · 课表资料整理

**本地识别课表，整理课程资料。** 一个完全离线的 Windows 桌面应用：从课表图片提取课程名，人工核对后创建课程文件夹，并将资料复制到指定分类。

**Turn a timetable into organized course folders.** CourseShelf is an offline Windows desktop app that reads a timetable image, lets you correct course names, creates course folders, and copies files into a chosen category.

[中文说明](#中文) · [English](#english)

## 中文

### 下载与使用

从 [Releases](https://github.com/lntanovo/CourseShelf/releases) 下载 `FilesOrganizer-Windows.zip`，**完整解压**后双击 `FilesOrganizer/FilesOrganizer.exe`。请保留同目录下的 `_internal` 文件夹；只复制 exe 无法运行。发布包包含 Qt 和本地 OCR 模型，无需安装 Python。

1. 在窗口顶部选择一个已有的本机文件夹作为**资料总目录**。完整路径始终显示在界面中，也可一键在资源管理器中打开。
2. 导入 PNG/JPG/JPEG 课表，点击“开始本地识别”，然后修改、添加或删除识别出的课程名。
3. 输入学期名称，预览并生成 `学期 / 课程 / 分类` 目录。每门课程固定包含 `课件`、`作业`、`复习资料`、`其他` 四类；重复生成会复用已有目录。
4. 选择或拖入一个文件，再选学期、课程和分类。核对界面中的来源与完整目标路径后复制。原文件保留；同名文件会自动加序号，不会覆盖。

资料保存在**你选择的普通文件夹**中，例如：

```text
资料总目录\2026秋季学期\通信原理\课件\讲义.pdf
```

右侧目录树和文件列表直接读取磁盘，复制后立即刷新。重启会恢复上次的资料总目录和查看位置。`%LOCALAPPDATA%\FilesOrganizerDemo\settings.json` 只保存这些路径设置，**不存放课程资料**。课表 OCR 在本机运行，不上传图片或文件。

### 从源码运行与打包

需要 64 位 Windows 10/11 和 CPython 3.12。在 PowerShell 中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
.\build.ps1
```

`build.ps1` 生成 `dist\FilesOrganizer\FilesOrganizer.exe`。分享时请压缩并发送整个 `dist\FilesOrganizer` 文件夹。打包脚本会移除可能从开发机 PATH 误收集、与 Qt 冲突的 `icuuc.dll`。

### 验证与限制

```powershell
.\.venv\Scripts\python.exe tests\smoke_demo.py
```

测试会在系统临时目录自动生成**虚构课表**和资料，不需要真实用户截图。它验证离线 OCR、9 门课程提取、人工修改、46 个目录生成及重复生成、同名复制、重启后路径与文件列表恢复、失效路径提示。开发时还用一张真实的清晰网页课表截图验证过 9 门课程；因包含真实课程安排与教师姓名，该图片不上传到公开仓库。

OCR 主要适用于清晰、带“课程代码 / 课程名称 / 课程类别”汇总表的课表。其他版式可能漏识别或混入无关文字，务必人工核对。当前版本没有自动分类、批量归档、全文检索、云同步或安装程序。

### 文件说明

| 文件 | 作用 |
| --- | --- |
| `app.py` | PySide6 桌面界面与交互 |
| `organizer.py` | 本地 OCR、课程提取、目录生成和安全复制 |
| `build.ps1` | 可重复执行的 Windows 打包脚本 |
| `requirements*.txt` | 运行与打包依赖版本 |
| `tests/smoke_demo.py` | 使用虚构课表的端到端测试 |

## English

### Download and use

Download `FilesOrganizer-Windows.zip` from [Releases](https://github.com/lntanovo/CourseShelf/releases), **extract the entire archive**, and double-click `FilesOrganizer/FilesOrganizer.exe`. Keep the `_internal` directory next to the executable. The portable release includes Qt and local OCR models; Python is not required on the user's PC.

1. Choose an existing local folder as the **library root** at the top of the window. Its full path stays visible and can be opened in File Explorer.
2. Select a PNG/JPG/JPEG timetable, run local OCR, and edit, add, or remove the proposed course names.
3. Enter a semester name, preview the plan, and create `semester / course / category` folders. Each course gets four fixed categories: lecture materials, assignments, review materials, and other. Existing folders are reused.
4. Choose or drop one file, select a semester, course, and category, and review the displayed source and full destination path before copying. The source remains intact; name collisions receive a numbered suffix.

Files live in the **ordinary folder you selected**, not inside the app or AppData. The directory tree and file list reflect the disk and refresh after a copy. The app restores the last library root and viewed folder on restart. `%LOCALAPPDATA%\FilesOrganizerDemo\settings.json` stores path preferences only. Timetable images and documents are never sent to a cloud service.

### Run from source and build

Use 64-bit Windows 10/11 and CPython 3.12. In PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
.\build.ps1
```

The build creates `dist\FilesOrganizer\FilesOrganizer.exe`. Distribute the **whole** `dist\FilesOrganizer` folder as an archive. The script removes an incompatible `icuuc.dll` that may be collected from a developer's PATH.

### Test and limitations

```powershell
.\.venv\Scripts\python.exe tests\smoke_demo.py
```

The test creates a **fictional timetable** and temporary files. It covers offline OCR, correction of course names, folder creation and reuse, safe duplicate copies, persistence, and invalid paths. A real clear web timetable with a course summary table was also checked during development; it is excluded from this public repository because it contains real teachers and schedule details.

OCR works best on clear timetables with a `course code / course name / course category` summary table. Other layouts may need substantial manual correction. Automatic classification, batch filing, full-text search, cloud sync, and an installer are outside this release.

### Project files

| File | Purpose |
| --- | --- |
| `app.py` | PySide6 desktop UI and workflow |
| `organizer.py` | Local OCR, course extraction, folder creation, and safe copying |
| `build.ps1` | Repeatable Windows packaging |
| `requirements*.txt` | Pinned runtime and build dependencies |
| `tests/smoke_demo.py` | End-to-end test with a fictional timetable |

## License / 许可证

[MIT](LICENSE). Third-party dependencies and OCR models retain their own licenses. / 第三方依赖及 OCR 模型遵循各自的许可证。
