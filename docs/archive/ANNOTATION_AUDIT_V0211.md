# v0.21.1 中文注释、解耦与原子性审计

审查基线：`origin/main` 的 `1bc6d73`，2026-10-03。审查对象是当前 Myth 仓库的生产 Python、前端、活跃测试和维护脚本；历史诊断独立归档。版本升级为 `0.21.1`。

## 结论

项目具备纯合同/策略、端口、应用用例及 I/O 适配器的基础边界，已有 Ticket/Receipt/UNKNOWN 核对协议。它**部分符合解耦与原子设计，尚未全面符合**：共享表写入、终结后的多仓储提交和大型门面仍需约束；数据库、文件和系统凭据库没有跨系统原子保证。

本轮把当前可确认的准入缺口修复并补回归，把注释要求写入宪法并加入 CI。没有用删测试、删迁移或抹去历史收据来制造“瘦身”。当前模块协作与剩余问题见 [CODE_GUIDE.md](../CODE_GUIDE.md)。

## 注释工作

- 所有 71 个生产 Python 文件补充简体中文模块职责；类/协议、函数、字段、构造持有状态、关键事务和恢复步骤均有说明。
- 初次逐项装配覆盖 148 个类、570 个函数、507 处属性/常量和 74 处事务/恢复边界；随后补齐条件/上下文内的局部声明及本轮新增协作函数。
- 前端 71 个命名函数、15 个主 state 字段和关键去重/generation/事件协作补中文说明；CSS/HTML 补装配与响应式边界，展开原有密集格式。
- 活跃测试逐项说明固定断言、替身范围、竞争与故障窗口；安装包脚本说明真实 HTTP/SQLite 和未测模型边界。
- 纠正不同作用域同名字段：OAuth `state` 是单次挑战，Web `active` 是本进程 Run 集；模型 SQL schema 不误称版本合同。
- 把关键旧英文恢复说明改为中文，去除 74 处内容相同的前置注释/docstring；27 个资源/事务构造器补具体生命周期说明。
- `scripts/check_annotations.py` 只验证说明存在，不能判断专家级正确性。其规则保留在 CI/AGENTS，字段语义、事务范围和设计原因需要随实现审阅。

源代码行数因展开格式和指导说明而增加。“瘦身”指减少不必要的业务耦合、加载依赖、重复实现/写入及错误的活跃入口，不以删说明减少行数。

## 发现与修正

| 已观察问题 | 修正 | 证据 |
| --- | --- | --- |
| 创建 Goal 和初始进度分两次提交 | 同一个 SQLite 事务写入两项 | 触发器拒绝第二次写入，两表均为空 |
| 精确文件入口先提交 Run，再准备副本和写 Intent | 事务外准备固定对象/私有基线，Run/账号/Action/Attempt/预留/事件共同准入 | 旧版注入副本失败得到 runs=1/accounts=2/actions=0；新版全部为零，修复后同 request_id 可重试 |
| 工作区直接写 Goal 表 | 个人状态所有者的 admission_snapshot/bind_admitted_run 加入同连接活动事务 | 真实 link 失败整项回滚；检查协作调用及连接身份 |
| 调度读取旧 Goal 缺进度时可能嵌套初始化事务 | 在已有准入事务调用个人状态的快照/补齐入口 | 删除旧进度夹具后 occurrence 与新进度一起正常准入 |
| Conversation 为取锁实例化 Exact 执行器 | 提取 `adapters/driver_lock.py`，两个执行器共享同一 OS 锁实现 | 既有第二 Driver 拒绝与真实硬退出测试仍通过 |
| 包入口连带导入 Runtime、供应商和认证依赖 | 保留公开类身份并按需导出 | 独立 `python -S` 进程只导入领域，未加载 sqlite3/urllib.request/jwt/keyring；公开类/目录兼容回归 |
| 同摘要对象并发发布在 Windows 出现权限竞争 | 发布失败后仅在目标字节完全相同才复用；无目标/冲突仍失败 | 实际双连接准入竞争；注入相同/错误赢家的两项恢复断言 |
| 重复调用 Goal bind_run | 从任务 Harness 去除重复关联写入 | create_turn 已原子绑定；完整 Harness 仍通过 |
| HTTP/供应商/组件版本硬编码过时 | 共用 `myth.__version__` | wheel/包版本、HTTP 标识与组件地图同步 |
| 旧 Lease 测试把回答结束当作 Driver 已释放 | 等待明确 DriverLeaseReleased 与实际 lease 清理 | 保留原释放断言，消除过早观察窗口 |

初始精确文件准入的两连接竞争测试强制两边先准备私有副本，再进入事务；只提交一个完整 Run/Action/Attempt。数据库失败或竞争败方可能留下无引用私有副本/对象，当前没有基于猜测删除它们的 GC。历史数据库中已经存在的半成品 Run 不自动伪造新证据，本轮改动阻止新半成品产生。

## 保留与清理清单

| 原位置 / 项目 | 结果 | 原因 |
| --- | --- | --- |
| `evals/foundation-v1/v2/v3.json` | 移至 `evals/archive/`，同步三组测试路径 | 仍有固定回归价值；移动时核对 SHA-256，题目字节不变 |
| `scripts/diagnose_v010.py` | 移至 `docs/archive/tools/`，同步历史报告入口 | 对应当时缺陷与接口，不是当前维护命令；补历史适用范围说明 |
| `rank_chunks`、`contextmanager`、`EvalReport` 的三处无用导入 | 删除 | Ruff 静态引用与实际调用链确认未使用 |
| 构建生成的 `build/` | 删除 639,640 字节旧包镜像 | 确认所有文件是 src 的可重建镜像，并核对目标绝对路径在此 checkout 内 |
| Exact 执行器内原锁实现、Conversation 的辅助 Exact 实例 | 合并到共享锁适配器 | 两条用例不为互斥承担对方业务依赖 |
| `MythKernel`、`LayerState`、`PlatformLayer`、`ControlPlane` 等薄别名 | 保留 | 公开兼容/历史合同；外部调用方迁移未获证实 |
| `aborted` 等旧数据库字段、additive migration | 保留 | 仍支撑旧数据库读取与协议映射；不是仅按名称可删除的版本残留 |
| 带版本号的活跃测试 | 保留 | 覆盖当前恢复、预算、上下文与权限不变量；版本号记录引入来源 |
| `.runtime` 内已有数据库、对象、收据、真实评测和发布物 | 保留 | 本地证据与可能未决状态，不因 ignored 就可删除 |
| planned 能力目录/公开端口 | 保留并标明成熟度 | 现有产品/兼容合同使用；没有新增自动执行后端或虚构可用性 |

## 仍未全面符合的部分

1. `SqliteControlService.command` 直接写对话 settings 与 Core control_revision；Resume 投影独立提交。不是全面的聚合写入隔离。
2. Conversation 的 finish_reply、经历记忆、Goal checkpoint 与 Driver finally 分别提交。旧 Run 防覆盖不等于终结链整体原子。
3. 对话仓储有 47 个函数，OAuth 模块 42 个，Web Workspace 门面 39 个；需按真实变更压力逐步分开职责，保留原子协调点。
4. 准入事务内的本地来源对象读取会延长写锁；完整扫描、固定快照与锁持续时间需在真实规模下测量。
5. OAuth 的远端调用、系统秘钥库和元数据文件分别完成；刷新锁不涵盖所有元数据/退出操作。
6. UNKNOWN 的真实外部核对、多文件断电原子性、分布式运行和长期语义验收未由本轮证明。

## 验证记录

- Windows / Python 3.13.9：完整 **213/213** 回归通过，27.867 秒；相对 main 新增 14 项测试。
- 新边界测试覆盖真实 SQLite 触发器、两连接竞争、准备失败、所有预算回滚、旧 Goal 初始化、同摘要对象发布核对。
- Python 注释前后 AST 去除 docstring 后比较，业务修改逐函数列出并单独审阅；未将重构伪装成纯注释修改。
- 三个 JS 的执行 AST 与 main 原版相同；Prettier 原始格式 debug-check、Node 语法检查通过。
- 当前 fixed daily Harness：两组各 30/30，合计 60/60，标记 `harness_fixture`。这不测量真实模型泛化能力。
- 最终生产说明范围为 71 个文件、149 个类、576 个函数；覆盖守卫检查 106 个 Python 文件、204 个类、895 个函数及 447 个生产属性声明，全部通过。
- compileall、三份 Node 语法检查、Ruff F401/F811 与 git diff --check 通过。
- 真实构建并安装 `myth_runtime-0.21.1-py3-none-any.whl`，在隔离安装目录验证 import、五份 HTTP 资源、Goal/Session、计划保存/暂停，全部通过。
- wheel SHA-256：`3af552a07d3894beb1d130f31569e78f6284a9a869a4b52be0a169c8283a0148`。
- 机器可读记录见 [annotation-audit-v0211.json](../evidence/annotation-audit-v0211.json)。远端 Windows/Linux × Python 3.12/3.13 结果以本次 PR 的 Checks 为准。
- 首次远端 Linux 两组通过，Windows 两组在检查器打印中文结果时被 cp1252 拒绝；检查器已固定 UTF-8 输出，并本地用 cp1252 重定向复现环境验证修复。

本轮不复用 v0.21 的真实模型 source digest 作为新源码证据，也不把旧真实模型报告升级为本轮测试。浏览器视觉布局没有在本轮重新实览；静态结构和安装 HTTP 资源验证保留各自范围。
