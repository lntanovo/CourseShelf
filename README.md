# CourseShelf · 离线课表与课程资料整理

Windows 10/11 便携桌面工具。课表识别、文件名建议、归档和搜索全部在本机完成，无账号、云服务、遥测或模型下载。

源码与构建脚本：[lntanovo/CourseShelf](https://github.com/lntanovo/CourseShelf)。

[1.5 只读操作记录](ACTIVITY_LOG_1.5.md) · [1.4 界面精简存档](UI_SIMPLIFICATION_1.4.md) · [1.3 技术文档存档](WORKFLOW_UPDATE_1.3.md) · [1.2 技术文档存档](TECHNICAL_DOCUMENTATION.md) · [主题与背景](UI_REFRESH.md)

## 启动与资料位置

完整解压 `dist/CourseShelf-1.5.0-Windows.zip`，双击 `CourseShelf/CourseShelf.exe`。保留 `_internal`、本地模型和许可文件；整个发布文件夹可以搬移，不需要安装 Python。本版未签名，Windows 可能显示 SmartScreen 提示。

选择一个已有的本机普通文件夹作为资料总目录。完整路径常驻窗口顶部，文件实际位于：

```text
资料总目录/学期/课程/分类/文件
```

不接受符号链接、目录联接、UNC 或映射网络盘作为资料根目录。磁盘始终是事实源；外部新增文件、课程和分类可刷新浏览。目录树按展开加载，不限制层数，大目录后台读取并分批显示。

## 操作流程

提供“整理资料”“资料库”“课表与课程”“生成目录”和“操作记录”五个页面，采用侧边导航。已有资料库启动后直接进入“整理资料”；首次使用可先选择“课表与课程”，再“生成目录”。右上角“外观与背景”可切换暖纸、鼠尾草、雾蓝、夜墨四套主题，也可选择本机 PNG/JPG/BMP 背景、调节可见度、移除背景或恢复默认。设置即时预览并自动保留。背景仅记录原图片路径，不复制、不上传；图片移走或损坏时自动回退为主题底色。最大图片文件 30 MiB，显示时会缩小解码。

1. 在“课表与课程”选择或拖入一张 PNG/JPG/JPEG 课表图，点击本地识别，核对候选课程；也可手动添加。换图或重新识别会确认，取消不会清空已核对的列表。模型在启动后空闲时预热并在本地进程中复用；识别阶段有文字提示，可随时取消或取消任务后退出。最近一张未变化图片的结果仅在内存缓存，内容哈希改变即重新识别；不保存课表图或识别文本到 AppData。
2. 在“生成目录”填写学期并预览。文件夹树按课程折叠，展开后查看分类。可选择或输入课设、实验等新分类，指定“全部课程”或某门课程后“加入预览”；预览不写盘，确认生成才建立目录。新课程默认含课件、作业、复习资料和其他。已有文件夹可直接浏览、搜索和归档，无需手动登记。部分创建失败会逐项报告并登记成功部分，重复登记保留分类顺序。
3. 在“整理资料”添加或拖入文件、文件夹，粘贴路径后按 Enter 追加。“应用高置信建议”只补全空目标，保留手选内容。用 Ctrl/Shift 多选文件，选择学期、课程、分类，再“设置目标”；可改为对全部待整理项设置。行内下拉框仍可逐项调整。无匹配、存在歧义或低置信模糊建议需手选。来源路径和匹配理由可悬停文件名查看。添加文件夹只读取当前层，子文件夹中的文件可单独添加。在资料库拖入课程/分类节点只填目标，不写入文件。
4. 点击“执行 N 项”才开始归档，N 只统计目标完整的待处理项；可选择仅执行选中项。未分配文件继续留在收件箱，成功项锁定，失败项单独重试。默认复制；移动必须明确选择，每项完整复制并验证大小与 SHA-256 后才删来源。同名不同内容保留两个，绝不覆盖；同名同内容默认跳过并显示已有路径。批次逐行报告成功、失败、跳过及原因，一项失败不中断其他项。取消保留已完成项，未处理项来源不变，不留临时复制文件。
5. 在“资料库”用学期、课程、分类下拉框筛选，并可叠加文件名和修改时间：今天、近7天、近30天、本月或日历自选区间。默认最新修改优先，也可按最早修改、名称或大小排序。文件夹树点击父目录时显示其分支中的文件，搜索结果附所在文件夹（最多 500 项）；清除筛选返回资料库根目录。启动或刷新时后台更新索引。选到已有资料库内部文件夹时，可保留资料库根目录并浏览该文件夹。双击打开文件，右键可打开、定位、复制路径；只有本应用有成功记录且内容未变的文件可重命名或回收。F5 刷新、Ctrl+F 搜索、Ctrl+O 打开，Delete 对选中项发起安全确认。

6. 在“操作记录”查看本机时间、中文操作名称、文件或目录内容及结果；最新记录在前，悬停查看完整路径或错误。进入页面和文件操作完成后刷新，也可手动刷新。此页不提供撤销或修改记录。

资料总目录内原有文件不能作为移动来源，可选择复制。本应用不修改、删除未由本应用归档的文件。资料库内单个文件的重命名或回收会核对归档记录与内容，只有本应用归档且未被修改的文件可操作。所有删除均走回收站，无永久删除回退。

## 本地数据与兼容

- 资料目录的 `.courseshelf.json` 只保存受管课程、分类顺序和显式设置的别名。v1 首次读取升级为 v2，原件备份为 `.courseshelf.json.bak`。遇到更高版本、损坏或迁移失败，仅浏览并禁用资料写入，不清空原文件。
- `%LOCALAPPDATA%/CourseShelf/settings.json` 保存资料路径和查看位置；首次兼容复制旧版 `FilesOrganizerDemo` 的设置、索引和历史，保留旧文件。
- 同目录的 `appearance.json` 独立保存主题、背景原图路径与可见度；切换资料库或查看位置不影响外观偏好。
- 同目录的 `index.db` 是文件名缓存，可删除或损坏后重建；外部改名后刷新不会保留可打开的幽灵文件。`history.db` 保留内部归档来源记录，用于保护非本应用归档的文件。“操作记录”页面只读显示当前资料库最近 500 条记录，不提供撤销入口；既有记录不清空。
- `logs/app.log` 本地轮转日志，5 MiB，保留 3 个备份。未捕获错误会弹出可复制的详情。不上传日志。
- 同一设置目录只允许一个界面实例，重复启动会提示并尝试激活已有窗口。
- 外部删除受管目录后，刷新会提示缺失；“重建选中空目录”仅创建空文件夹，不能恢复文件内容。

## 卸载

先关闭 CourseShelf，运行同目录的 `uninstall.exe`。卸载仅删除发布清单中 SHA-256 匹配的程序文件，可选择清除路径、主题和背景设置；资料目录、原背景图片、未登记文件和用户自建空目录保留。日志和操作历史不会随清除设置而删除。便携版没有系统安装项。

## 源码运行与构建

需要 64 位 Windows 和 Python 3.12。一次性安装开发依赖与官方 UPX 构建工具（安装阶段联网，应用运行无需网络）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\tools\setup_upx.ps1
# 如需代理：.\tools\setup_upx.ps1 -Proxy http://127.0.0.1:7897
.\.venv\Scripts\python.exe app.py
.\tests\verify_milestone.ps1 -Milestone local
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports .
```

`build.ps1` 可单独执行。它生成图标、版本信息、发布清单、许可目录和版本化 zip；只压缩已验证的 OCR/数值库，Qt 和 Python 运行库保持原样。验收脚本使用虚构课表与系统临时目录，执行构建和搬移后的离线 OCR、归档与卸载测试。私人 `课表.png` 只读且已排除提交；CI 始终使用 `-UseFictionalSample`。本地构建不会自动上传 GitHub 或创建 Release。

| 路径 | 作用 |
| --- | --- |
| `app.py` | 程序与验证命令入口 |
| `ui/` | 主窗口、标签页、控件和统一安全确认框 |
| `tasks/` | 可取消的 OCR、批量归档、索引、目录读取和撤销任务 |
| `services/` | 清单、文件操作、文件名匹配、索引和操作历史 |
| 根目录同名模块 | 兼容上一版的导入入口 |
| `tools/`、`build.ps1` | 构建工具、图标、许可收集、发布压缩包 |
| `tests/` | 临时数据验收与虚构 OCR 课表 |

详细实施、真实命令输出和 V01–V15 结果见 [IMPROVEMENT_VALIDATION.md](IMPROVEMENT_VALIDATION.md)。

## 范围与局限

OCR 适合清晰课程汇总表，支持课程名/科目、编号/课程编号、类型/类别等表头同义词。格子周课表、手机截图和复杂版式仍可能需要人工修正；未实现框选、坐标行聚类或可靠的逐课程置信度。未用非汇总表真实课表验证。本轮不提供跨文件名内容查重、正文检索、云同步、标签、自动监控或安装程序。

## English

Extract the complete CourseShelf folder and run `CourseShelf.exe`. All OCR, suggestions, filing and search stay local. Select an existing local library folder. Add multiple files/folders to the inbox (recursion is opt-in), apply confident suggestions, review every target, and execute. Copy is the default; moving verifies size and SHA-256 before removing the source. No file is overwritten. Identical named content is skipped, failures are isolated, and cancellation preserves completed items.

Search uses a rebuildable local cache. Internal filing records protect existing user materials. A read-only activity page shows local times, operations and results. Undo controls, the advanced inbox panel, and the category/alias management panel are absent. Only recorded and unchanged archived files can be renamed or trashed individually. The portable uninstaller preserves user materials and unlisted files. OCR layout support remains limited; manually review all candidates.

## License

[MIT](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the release's `licenses/` folder for Qt/PySide6 LGPL and other dependency/model notices. Qt DLLs remain dynamically linked and replaceable.
