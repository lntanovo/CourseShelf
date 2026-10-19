# CourseShelf 本轮实施与验收

日期：2026-10-19。所有测试数据使用系统临时目录；未读取或改写私人课表。

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

