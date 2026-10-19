# CourseShelf 本轮实施与验收

> 本文记录 1.1.0 的 M0–M7 历史验收。1.2.0 当前界面、主题、背景与发布记录见 [UI_REFRESH.md](UI_REFRESH.md)。

实施：2026-10-19 至 2026-10-20。所有测试数据使用系统临时目录；本轮未读取或改写私人课表。执行顺序为 M0 → M1 → M2 → M3 → M4 → M5 → M6a/M6b → M7。

## M0 基线（已通过）

实际命令（项目根目录 PowerShell）：

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py organizer.py catalog.py classifier.py file_ops.py uninstaller.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_optimization.py -v
.\.venv\Scripts\python.exe tests\smoke_demo.py
.\build.ps1
.\tests\packed_acceptance.ps1 -UseFictionalSample
```

结果：语法退出 0，6/6 测试通过，虚构课表 OCR 9/9（socket 拦截），46 个目录首次创建、二次全部复用；复制保留源，同名加序号；重启恢复路径。未复现旧审计的 ACL 问题。

打包后原始输出：

```text
Relocated exe OCR: 9 courses
Relocated exe archive: test file copied into user library; source retained
Relocated GUI app opened: PID 4788
Relocated uninstall: 310 owned files removed; user material and empty folder preserved
```

发布基线：403039388 bytes（384.37 MiB）。完整输出保存在 `artifacts/improvement/m0-*.log`。

## 验收冲突裁决

- B11 的覆盖选项违反 §7.2，省略覆盖，仅提供保留两个与跳过。
- B13 的撤销删除仅对本应用有成功记录且大小、SHA-256 均匹配的目标执行，并只送入回收站。
- U02 对未受管用户文件的重命名、删除违反 §7.3；仅允许打开、定位和复制路径。
- 分类整体重命名与回收也受 §7.3 约束：后台逐文件核验成功归档记录、大小和 SHA-256，任何未登记、内容已变或链接文件均阻止整目录操作。课程/分类登记不自动授予其既有文件的修改权限。
- 删除索引可重建的是文件缓存；持久操作历史不属于可重建缓存，单独保存，避免删索引丢撤销依据。

## M1 止血（通过）

执行 tests/verify_milestone.ps1 -Milestone m1（语法 → 10 项单元/回归 → 离线冒烟 → build.ps1 → 搬移打包验收）。全部通过，日志见 artifacts/improvement/m1-*.log。注入归档 RuntimeError 后日志含 traceback，弹窗详情可复制；OCR 关闭可取消且无存活线程。清单版本迁移入口已建立，v1→v2 在 M5 启用。


## M2 批量归档（通过）

执行 tests/verify_milestone.ps1 -Milestone m2。13 项测试、离线冒烟、打包与搬移验收全通过（原始日志 m2-*.log）。20 项中 18 成功/2 待手选，3 组同名保留两个；中途取消后无 partial 文件；20 项 PermissionError 注入逐项失败并可全部重试。收件箱替换后选中行同步错误由冒烟发现并修复，修复后重跑全套。默认复制，批次与行内均可显式选择移动。


## M3 索引与搜索（通过）

执行 tests/verify_milestone.ps1 -Milestone m3。15 项测试、离线冒烟、打包与搬移验收全通过。10 门课 × 50 文件：删除 index.db 后重启后台恢复；外部改名刷新无幽灵记录；损坏 SQLite 缓存移存后重建。修复 SQL LIKE 转义与取消扫描连接释放，并重跑。文件缓存与持久历史分库，历史表已建立。完整日志 m3-*.log。


## M4 历史、撤销、去重（通过）

执行 tests/verify_milestone.ps1 -Milestone m4。17 项测试、冒烟、打包及搬移验收通过。记录逐项 copy/move 及目录操作和撤销；目标提交时复用流式 SHA-256，移动删除来源前先存校验记录。复制撤销走回收站；目标被修改、原来源被占用、重复撤销均拒绝。移动撤销保持原文件名（即使归档时加过序号）。同名同内容跳过，同名不同内容保留两个。非同名内容查重是可选项，本轮未实现。目录审计写失败写入日志，仍优先保证成功目录登记清单。原始输出 m4-*.log。


## M5 匹配与别名（通过）

执行 tests/verify_milestone.ps1 -Milestone m5。18 项测试、离线冒烟、构建、搬移验收全通过。启用 schema 2，验证 v1 备份和分类顺序不变，迁移注入失败不改原清单。高数别名唯一命中；共享别名不选课；模糊匹配低置信，不自动应用。别名只通过明确编辑或一次性确认保存。原始输出 m5-*.log。


## M6 架构与性能（通过）

先以 M6a 独立提交纯搬运（18 项测试通过），再实施扫描改动。执行 tests/verify_milestone.ps1 -Milestone m6：19 项测试、冒烟、构建与搬移验收通过。MainWindow 175 行；services/ui/tasks 分层，根模块兼容导入。删除两套死代码。目录树懒加载无深度上限，大目录后台枚举、每批 64 行填充，分类统计后台完成。5000 文件最大事件循环间隔 26.5 ms（阈值 200 ms）；mock 断言一次刷新 load_catalog 只调用 1 次。路径设置延迟合并写入并在关闭时刷新。拒绝 UNC/映射网络根目录。原始日志 m6-*.log。

## M7 体验与发布（本机验收通过，外部验收保留）

统一 CourseShelf 标题、exe 与 AppData，兼容复制旧设置而保留旧文件；增加数字排序、文件图标、右键菜单、安全文件操作与快捷键。OCR 使用可取消的本地常驻进程，空闲预热并显示阶段；复用模型及最近一张未变化图片的内存结果。补充表头同义词，未扩展为通用周课表解析器。

发布增加多尺寸图标、1.1.0 版本资源、原始依赖许可证、NOTICE、版本化 zip 与 manifest。裁剪未用 Qt 模块/插件、视频解码器及重复库；仅对 cv2 与 OpenBLAS 使用构建工具 UPX，并执行其完整性检查，Qt/Python 保持原样。初次尝试压缩 ONNX/MSVC 库被 GUARD_CF 保护拒绝后已撤回，没有强制压缩；最终构建和实际离线 OCR 通过。配置 Windows CI、ruff 与宽松 mypy。

最后一次实际执行：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports .
.\.venv\Scripts\python.exe -m pip check
.\tests\verify_milestone.ps1 -Milestone m7
```

`verify_milestone.ps1` 实际依次执行根模块及 services/ui/tasks 的 `py_compile`、`unittest discover -s tests -p 'test_*.py' -v`、`tests/smoke_demo.py`、`build.ps1`、`tests/packed_acceptance.ps1 -UseFictionalSample`。每一步非零即失败，原始输出保存为 `artifacts/improvement/m7-{syntax,unit,smoke,build,packed}.log`。额外检查见 `m7-{ruff,mypy,pip-check,lint-probe}.log`。

实际输出（末次完整验收）：

```text
All checks passed!
Success: no issues found in 41 source files
No broken requirements found.
Ran 27 tests in 15.881s
OK
U03 cached OCR: 3.092s -> 0.047s
V14: 5000 files, maximum event-loop gap 14.4 ms
OCR: 9/9 table courses found; socket access blocked
Directories: 46 created, second run reused all 46
Copy: source retained, identical duplicate skipped, prior target unchanged
Restart: root, selected directory, and existing files restored
Missing remembered root: warning shown, path not recreated
Name collision: rejected
Release bytes: 175263037
Relocated exe OCR: 9 courses
Cached exe OCR: 4.40432119999969 s then 0.046815499998047 s
Relocated exe archive: test file copied into user library; source retained
Relocated GUI app opened: PID 16144
Relocated uninstall: 246 owned files removed; user material and empty folder preserved
m7 verified
```

缓存耗时只代表同一张未变化图片的再次识别，不能推广为任意新图片的性能。另用相同大小、相同 mtime、不同内容的输入验证哈希可使结果缓存失效。故意在临时目录添加未使用的 `import math`，ruff 返回 1 并报告 `F401`，探针未留入源码。mypy 当前不检查未注解函数体，UI/tests 允许错误，属于渐进类型检查。

完整里程碑执行记录：

| 里程碑 | 实际命令 | 单元真实输出 | 全流程 |
| --- | --- | --- | --- |
| M0 | 上文逐条命令 | `Ran 6 tests in 0.596s` / `OK` | 语法、冒烟、构建、搬移通过 |
| M1 | `./tests/verify_milestone.ps1 -Milestone m1` | `Ran 10 tests in 0.694s` / `OK` | 全部通过 |
| M2 | `./tests/verify_milestone.ps1 -Milestone m2` | `Ran 13 tests in 2.848s` / `OK` | 全部通过 |
| M3 | `./tests/verify_milestone.ps1 -Milestone m3` | `Ran 15 tests in 3.378s` / `OK` | 全部通过 |
| M4 | `./tests/verify_milestone.ps1 -Milestone m4` | `Ran 17 tests in 9.818s` / `OK` | 全部通过 |
| M5 | `./tests/verify_milestone.ps1 -Milestone m5` | `Ran 18 tests in 9.610s` / `OK` | 全部通过 |
| M6 | `./tests/verify_milestone.ps1 -Milestone m6` | `Ran 19 tests in 24.850s` / `OK` | 全部通过 |
| M7 | 上文命令及 `-Milestone m7` | `Ran 27 tests in 15.881s` / `OK` | 本机全部通过 |

各次完整原始输出分别保存在 `artifacts/improvement/m0-*.log` 至 `m7-*.log`。这些是本机验收产物，未提交 Git。M1 安全基线已有本地 tag `courseshelf-m1`；后续里程碑分独立本地提交。M7 末次中文窗口截图已人工检查，收件箱七列可见，长文本可横向滚动或悬停查看。

## V01–V15 逐条结果

“通过”指以下注明的本机自动化覆盖，并不表示跨机器人工验收。

| 编号 | 结果 | 实测证据与边界 |
| --- | --- | --- |
| V01 | 通过 | 20 文件，3 组同名各 3 个；18 成功、2 未匹配跳过并提示需手选，源与目标字节一致，无覆盖。多文件/文件夹入箱另有 UI 测试。 |
| V02 | 通过 | 第一项后取消，1 成功、19 跳过，未完成来源不变，无 `.courseshelf-partial-*`；另覆盖写入/删除源失败。 |
| V03 | 通过 | 用 `PermissionError` 模拟只读目标，20 项全失败，界面逐行显示错误、汇总失败 20，点击仅重试失败项后 20 项成功。未改真实磁盘 ACL。 |
| V04 | 通过 | `课件` 同名文件阻挡，其他默认分类成功并入清单，缺失检测及部分恢复后登记通过。创建函数返回逐项失败列表供界面显示。 |
| V05 | 通过 | schema 99 原件字节不变，窗口仍能浏览磁盘并显示更新版本警告，写操作拒绝。 |
| V06 | 通过 | 统一确认框 default/escape 均 No；用 QTest 实际发送 Return，返回 No。 |
| V07 | 通过 | 真实 OCR 启动后关闭窗口，确认取消，worker 结束、窗口关闭，无存活 QThread 警告。 |
| V08 | 通过 | 在 FileWorker 的归档 transfer 注入 RuntimeError，日志含 traceback；错误框详情可复制，剪贴板与详情一致。批量异常亦接同一报告通道。 |
| V09 | 通过 | 另起 Python 进程持有同一 QLockFile，当前 acquire_instance 拒绝并触发已运行提示；释放后可重新取得锁。覆盖跨进程互斥，非人工双击录像。 |
| V10 | 通过 | 删除索引后新窗口后台重建，10 课×50 文件可搜索；外部改名无幽灵，损坏索引移存后重建。 |
| V11 | 通过 | 复制撤销调用回收站并保留源；目标内容变化拒绝，移动原路径被占用拒绝；重复撤销拒绝。 |
| V12 | 通过 | 同名同大小同 SHA-256 默认跳过，不产生副本；不同内容保留两个。 |
| V13 | 通过 | v1 备份迁移，显式别名正确建议，共享别名留空；模糊建议不自动应用。 |
| V14 | 通过 | 5000 文件深层目录，最大事件循环间隔 14.4 ms <200 ms；刷新清单读取断言 1 次。 |
| V15 | 未实现（异机验收） | 本机复制到全新临时路径后，exe 的离线 OCR、归档、GUI 存活、卸载保护全部通过，发布体积满足要求；没有第二台机器，无法声明完整场景通过。 |

新增安全回归还覆盖分类包含手放文件、内容变化文件时禁止整体重命名/回收，取消后原路径保留，以及正常分类重命名后文件受管记录随路径更新。所有文件测试均在临时目录，未使用私人课表图片。

## 发布体积与完整性

| 产物 | 字节 | MiB |
| --- | ---: | ---: |
| M0 原发布目录 | 403039388 | 384.37 |
| M7 `dist/CourseShelf` | 175263037 | 167.14 |
| M7 `dist/CourseShelf-1.1.0-Windows.zip` | 104515033 | 99.67 |

发布目录缩小 56.51%，小于 180 MiB。旧版 `dist/FilesOrganizer` 保留，当前应分发 CourseShelf 1.1.0 的 zip。

最终 zip SHA-256：`47f7d14c8080a70871eeabd536b07f3d89f75ec79e502687276b504fe13bd560`。

逐项核对 manifest 的 246 个受管文件校验和，zip 的 248 个文件与发布目录集合及 SHA-256 完全一致（额外两个为 manifest 和卸载器）；读取 zip 同时通过 CRC 检查。ICO 包含 16/32/48/256，PE ProductName=CourseShelf、FileVersion=1.1.0，发布 README 与当前源码逐字节一致。实际输出保存为 `artifacts/improvement/m7-artifact.log`：

```text
ZIP matches release: 248 files; CRC and SHA-256 verified
Manifest: 246 owned checksums verified; icon: 16/32/48/256
Release README matches current source; PE version independently checked: 1.1.0 CourseShelf
```

## 未完成与交付边界

- U04 只完成规格 M7 允许的最低项“表头同义词表”。通用坐标行聚类、手动框选、逐课程置信度未实现；未获取并验证非汇总表真实课表，README 已如实标明。
- Q03 已有可执行 Windows CI，但本轮没有推送或 PR，远端 CI 通过这一验收未完成；本机执行了相同流水线和 lint 故障探针。
- V15 的真正异机测试未执行；同机换路径不等于另一台机器。Q02 未签名：本轮无签名证书，符合规格允许的范围。
- B14 的跨文件名内容查重属于可选项，本轮未实现。历史保存在本机，与旧绝对路径关联；搬移资料目录或换机器不自动迁移撤销依据。
- 覆盖归档、永久删除、修改未受管文件均依 §7 排除。没有添加云同步、正文检索、标签等长期功能。

