# CourseShelf 1.2.0 界面更新

日期：2026-10-20。目的：减少一次性显示的操作，让日常整理优先，课表和目录管理按需进入。桌面实现仍使用 PySide6，原有默认复制、显式移动、禁止覆盖、回收站删除及 SHA-256 撤销保护保留。

## 视觉与布局

- “柔和文具”方向：194px 侧栏、单页工作区、圆角与低对比边线，微软雅黑正文 13px、页面标题 27px。资料路径始终可见，主题使用统一语义色。
- 导航为整理资料、资料库、课表与课程、生成目录、操作记录。已有有效资料库启动后进入整理资料，首次使用进入课表设置。原页面控制器和课程/分类编辑保留。
- 收件箱以文件与目标为主，原有左右并排的浏览区独立为资料库页面。执行区固定在底部；进阶选项可折叠，展开后自动滚动至详情。小窗口自动隐藏收件箱大小列并调整目标列宽。
- 分类管理折叠；目录修复仅在出现缺失时显示。Ctrl+F 跳转资料库并聚焦搜索。

| 主题 | 背景 | 表面 | 主要文字 | 强调色 |
| --- | --- | --- | --- | --- |
| 暖纸（默认） | `#F5F2EB` | `#FFFDFA` | `#35433D` | `#566E5E` |
| 鼠尾草 | `#EDF2EC` | `#FAFCF8` | `#33483B` | `#526F54` |
| 雾蓝 | `#EDF2F5` | `#FAFCFD` | `#344752` | `#4D7183` |
| 夜墨 | `#202725` | `#29312E` | `#E2E7DF` | `#B1C6A6` |

## 主题与背景

右上角“外观与背景”即时切换主题。可从本机选择 PNG/JPG/JPEG/BMP，调节可见度 0–80%、移除背景，或恢复默认外观。文件上限 30 MiB，解码显示最长边 2048，保持比例居中裁切；不改原文件。工作面板保持实色，避免背景干扰文字。

`%LOCALAPPDATA%/CourseShelf/appearance.json` 独立保存主题、背景原路径和可见度，250ms 合并写入并在关闭时刷新；切换资料库/查看目录不会覆盖它。恢复默认仅重置外观。原图不复制、不上传、不纳入仓库；失效图回退到底色并提示。卸载时可清除外观设置，原背景图片、用户资料和历史仍保留。

## 实际验收

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports .
.\tests\verify_milestone.ps1 -Milestone ui-refresh
# 补充统一 Windows 临时路径表示后，再跑全部单元测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.venv\Scripts\python.exe tools\preview_ui.py
```

最后单元输出：`Ran 32 tests in 16.950s`、`OK`；5000 文件最大事件循环间隔 19.8ms。ruff 通过，宽松 mypy 检查 45 个文件通过。新增 5 项测试覆盖四主题切换、重启恢复、资料路径不覆盖外观、错误/失效图片回退、移除背景保留原图、恢复默认不改资料、小窗口执行按钮可达及多文件拖放。

完整语法、单元、离线 OCR 冒烟、构建及搬移验证日志：`artifacts/improvement/ui-refresh-*.log`；最终补跑单元日志 `ui-final-unit.log`。真实打包输出：

```text
Relocated exe OCR: 9 courses
Cached exe OCR: 4.6160243000013 s then 0.0478667999996105 s
Relocated exe archive: test file copied into user library; source retained
Relocated GUI app opened: PID 23604
Relocated uninstall: 246 owned files removed; user material and empty folder preserved
Appearance: saved ink theme and local background launch; preferences cleared, original image preserved
ui-refresh verified
```

可重复截图见 `tools/preview_ui.py`，仅使用临时文件、虚构课程及临时绘制的背景。检查了四主题、背景、外观面板、1360×880 与 1040×720 布局。截图位于 `artifacts/ui-refresh`，不提交私人图片。截图与运行数据不是应用内置背景素材。

| 发布产物 | 字节 | MiB |
| --- | ---: | ---: |
| `dist/CourseShelf` | 175280528 | 167.16 |
| `dist/CourseShelf-1.2.0-Windows.zip` | 104532028 | 99.69 |

zip SHA-256：`e36c9d3bae3ad0d1de9924c757ba3f397ecdf563d8acca60807fe72ea78b03cf`。

上一轮 GitHub CI 在 Windows 的 `RUNNER~1` 短路径与 `runneradmin` 长路径混用时失败；本轮将临时测试根目录统一为 `Path.resolve()`，与界面既有的路径规范化一致，保留原安全断言。本轮提交前仍以本机验收为证，不把尚未完成的远端流水线报告为成功。
