# CourseShelf · 课表资料整理 / Timetable File Organizer

完全本地的 Windows 桌面工具：识别课表、人工核对课程、建立课程分类，并把资料复制或移动到指定目录。Offline Windows desktop app for timetable OCR and course file organization.

## 中文

### 启动和资料位置

完整解压 `dist\FilesOrganizer` 发布文件夹，双击其中的 `FilesOrganizer.exe`。`_internal` 文件夹和本地 OCR 模型必须与 exe 一起保留。发布文件夹可以搬到别的位置；不需要开发机的 Python 或虚拟环境。本地构建不会自动上传 GitHub 或创建 Release。

首次运行，点击顶部“选择资料目录”，选择一个**已有的普通文件夹**。完整路径常驻窗口顶部，可用“打开资料目录”在资源管理器中查看。资料实际保存在：

```text
你选择的资料总目录\学期\课程\分类\文件
```

资料目录中的 `.courseshelf.json` 只记录应用管理的目录清单；真实文件仍以磁盘为准。`%LOCALAPPDATA%\FilesOrganizerDemo\settings.json` 只保存上次使用的路径，不保存课表图片或课程资料。把资料总目录搬走后，需要在界面重新选择新位置。

### 操作流程

1. 在第 ① 步选择或拖入**一张** PNG/JPG/JPEG 课表图，点击“开始本地识别”，再核对、修改课程名。图片放下后不会自动识别；重新识别会询问是否替换已编辑的列表。也可以手动录入课程。
2. 在第 ② 步填写学期并预览。预览不写磁盘；“确认生成目录”才创建。点击“下一步”时若还有待建目录，会弹窗提供“创建并继续 / 返回检查 / 取消”。新课程默认建 `课件`、`作业`、`复习资料`、`其他` 四类。
3. 在第 ② 步选择课程后，可添加、重命名、将分类送入 Windows 回收站、恢复默认分类，或把已有课程目录纳入管理。删除分类前显示路径和内容数量。普通重复生成不会补回已删除的分类。
4. 在第 ③ 步向收件箱添加多个文件或文件夹（默认不递归，可显式包含子文件夹）。点击“应用全部高置信建议”，逐行核对课程、分类和操作；无匹配项需手选。文件名规则会给出课程、分类建议和理由；含糊时请手动选。拖到右侧课程或分类节点会优先使用该节点。可在行内或下方编辑选中行的目标，选择“复制（默认）”或“移动”后点击“执行 N 项”。拖入本身不会修改文件。
5. 复制会保留来源；移动先完整复制并验证大小与 SHA-256，再删除来源。同名文件加序号，绝不覆盖。文件操作有进度和取消按钮，逐行报告成功/跳过/失败及原因；失败不会中断整批，可仅重试失败项。同名策略为保留两个（默认）或跳过，不提供覆盖。已成功项不会被再次执行。成功后右侧文件列表立即刷新。

右侧目录树直接读取磁盘；重启后恢复资料总目录和上次查看的位置。外部删除受管目录后，刷新会提示缺失；点击“重建选中空目录”只建立空文件夹，**不能恢复丢失的文件内容**。外部新建的分类刷新后可浏览、归档，也可把该课程重新纳入管理。

### 操作历史与撤销

第 ④ 页按批次显示本机操作历史。复制撤销前核对目标的大小与 SHA-256，匹配后送入回收站；移动撤销会移回原路径，原路径已占用则拒绝覆盖。修改过的目标无法撤销，分类回收站记录需手动还原。不支持撤销建目录、分类重命名或撤销本身。

同名同内容文件默认跳过，并显示现有路径；同名不同内容仍按保留两个或跳过策略处理。操作历史位于 AppData 的 `history.db`，删除 `index.db` 不会丢失历史。历史不随资料目录搬到另一台机器。

### 文件搜索

右侧可按文件名、课程、分类搜索整个资料目录（最多显示 500 项）。启动或刷新时后台增量扫描，外部改名后刷新即可更新。`%LOCALAPPDATA%\FilesOrganizerDemo\index.db` 是可重建缓存，删除或损坏后重新扫描恢复；它不决定磁盘上的文件是否存在。

### 卸载便携版

关闭 CourseShelf 后，双击发布文件夹中的 `uninstall.exe`。它会说明要清理的发布文件夹，并询问是否清除本机保存的路径设置。只删除发布清单中校验匹配的程序文件；用户自行放进发布目录的文件及资料总目录不会删除。便携版没有 Windows“已安装应用”注册项。

### 从源码运行、测试和重新打包

需要 64 位 Windows 10/11 和 CPython 3.12。在 PowerShell 中：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_optimization.py -v
.\.venv\Scripts\python.exe tests\smoke_demo.py
.\build.ps1
.\tests\packed_acceptance.ps1
```

输出为 `dist\FilesOrganizer\FilesOrganizer.exe`、`uninstall.exe`、`release-manifest.json` 和 `_internal`。分享时必须压缩并发送**整个** `dist\FilesOrganizer` 文件夹。`build.ps1` 可重复运行，清理 PyInstaller 旧产物并重建发布清单。`课表.png` 是本地真实回归图片，含私人课程信息，已在 `.gitignore` 中排除。
`packed_acceptance.ps1` 会把发布文件夹复制到系统临时目录，在那里运行 exe、离线 OCR 和卸载测试；若本机没有私人 `课表.png`，它会生成虚构课表。测试资料与设置也只放在临时目录，结束后清理副本。
本轮逐项结果见 [验收记录](VALIDATION.md)。

### 文件说明与范围

| 文件 | 作用 |
| --- | --- |
| `app.py` | PySide6 界面、交互和后台任务 |
| `organizer.py` | 本地 RapidOCR、课程提取和原有基础文件操作 |
| `catalog.py` | 每课分类管理、受管目录清单、外部缺失检测 |
| `classifier.py` | 仅根据文件名给出可解释的本地建议 |
| `file_ops.py` | 分块复制/移动、校验、取消及同名保护 |
| `uninstaller.py` | 便携版卸载程序源代码 |
| `build.ps1` | 一键重建 exe、运行组件和发布清单 |
| `tests/` | 虚构课表和临时目录验收测试 |

本版使用批量收件箱，单文件也通过同一流程归档。OCR 对清晰的课程汇总表效果较好，其他版式可能需要手工修正。未实现全文检索、云同步、自动监控、安装程序或文件内容理解。

## English

Extract the entire `dist\FilesOrganizer` folder and double-click `FilesOrganizer.exe`. Keep `_internal` beside it; the release includes Qt and local OCR models. Choose an existing ordinary folder as the library root. Your documents live at `root\semester\course\category\file`, never inside AppData. The app stores only path preferences in `%LOCALAPPDATA%\FilesOrganizerDemo\settings.json` and a lightweight folder manifest in the chosen root.

Drop or select one PNG/JPG/JPEG timetable, run local OCR, and correct the course names. Previewing folders does not create them; the Next button asks before creating missing folders. Manage categories per course, including Recycle Bin deletion. Add multiple documents or folders to the inbox (recursion is opt-in), apply confident suggestions, then review each target before executing. Unmatched rows require manual selection. Failed rows can be retried; cancellation preserves completed items. **Copy is the default**; move requires explicit selection, verifies the destination, then removes the source. Name collisions receive a numbered copy without overwriting. Refresh detects externally deleted managed folders and offers to recreate empty folders; it cannot recover deleted contents.

For a portable uninstall, close the app and double-click `uninstall.exe` in the release folder. It removes only matching application files from the release manifest and optionally clears path settings. It never deletes your library root or user files placed beside the app. Build from source with the PowerShell commands above; distribute the whole release folder. This version has no cloud service, full-text search, or installer.

## License / 许可证

[MIT](LICENSE). Third-party packages and OCR models retain their own licenses. / 第三方依赖和 OCR 模型遵循各自许可证。
