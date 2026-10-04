# Myth 安全与性能审查

审查日期：2026-10-03。基线为 GitHub `main` 的 `8b2e415c2ba171282b7be5e65aaca638d3478345`，代码与包装版本均为 **0.23.0**；原 README 的 0.21.1 已校正。本次在独立审查副本修改，未覆盖原工作目录。

## 结论与覆盖

原生 ChatGPT 登录的方向正确：Myth 自有 dynamic registration、PKCE、state、nonce、固定 issuer、系统凭据库。实际实现仍存在需要修复的泄露和恢复窗口，不能仅凭已有 OAuth 测试通过就认为安全。

本次覆盖全部 **72 个原有 Python 模块**、新增的 `auth/transport.py`、5 个前端文件，以及依赖、CI、启动入口。方法是源码合同审阅、完整 AST 模块清单、危险 I/O 与输出点扫描、现有回归及新反例。登录、供应商、项目工具、Web 和策略发布是重点逐分支核对；纯目录/协议模块核对其合同与既有测试。逐文件记录见后表。该审查没有给出“绝对安全”或生产认证保证。

- 基线：223 项测试通过。
- 修改后：**268 项测试通过**，其中新增 43 项安全/性能边界测试、2 项策略竞争窗口测试。
- 实际 Windows 凭据库：约 **33 KB** 合成记录保存、轮换、读取、删除通过；未读取任何已有账户。
- 完成 Python 编译、简体中文指导注释检查、三个前端 JS 语法检查、diff 空白检查、wheel 构建与安装后的本地 Demo 验收。
- 当前文件与基线可达历史 714 个 blob 未命中脚本检查的 5 类常见秘钥格式。模式扫描不识别所有任意口令、编码后的秘密或未进入 Git 的文件。
- 未实际登录 ChatGPT、未使用用户 API Key、未发送真实模型推理；远端兼容性、账户额度、真实 TTFT 和吞吐均未验证。

合成证据见 [JSON 记录](evidence/security-performance-2026-10-03.json)。测试通过证明相应夹具中的合同，不证明任意代理、操作系统或供应商行为。

## 威胁边界

目标是本机、单用户、loopback 工作台：防跨站浏览器请求、恶意项目文件/链接/配置、供应商错误回显、误存凭据、并发刷新与退出、崩溃后重复派发。OAuth、API Key 与项目数据分开处理。

系统凭据库能保护静态凭据，不隔离同一 OS 用户下的恶意程序、调试器、内存转储或篡改过的 Python/keyring 模块。Web 没有多用户登录/RBAC，不能作为共享网络服务部署。认证锁按同一个 Runtime 根协调；复制认证元数据后跨多个根共享同一 profile，不属于本次已验证的并发合同。

## 已修复问题

这里的优先级表示整改紧迫性；不表示发现用户账户已经被攻击或秘钥已经泄露。

| 优先级 | 原行为 / 反例 | 修改后的行为与证据 |
|---|---|---|
| P1 | 回访授权把 `id_token_hint` 放入授权 URL，该 URL 又进入 Web JSON/浏览器 | 省略官方允许省略的可选 ID Token；保留必要的一次性授权参数，verifier 不离开后端。测试重登录 JSON/URL 不含 ID Token |
| P1 | `urllib` 自动重定向可能把 Bearer 认证头交给下一跳 | 凭据请求全部使用独立、不跟随重定向的 opener；真实 loopback 夹具验证 301/302/303/307/308 均无第二跳 |
| P1 | 刷新和退出使用不同锁，晚到刷新可把退出后凭据重新保存 | 登录、刷新、选择、状态与退出共用聚合锁；两管理器交错测试验证退出清掉最终轮换值，凭据不会复活 |
| P1 | 刷新请求发出后进程退出，下次仍可能提交旧 refresh token | 派发前持久 `refresh_pending`；未确认轮换时不重放旧值。崩溃夹具验证后续请求必须重新登录 |
| P1 | 退出后未完成的旧登录仍可能保存凭据 | 退出先保存 signed_out、更新 login epoch、取消内存挑战；另一个管理器的旧回调也被拒绝 |
| P1 | Windows 凭据库单条容量无法容纳较长 OAuth 记录 | ASCII JSON 分块，每块至多 1000 字符；先登记代次、最后切 active，带摘要与有界清单。实际 WinVault 和中途断写/旧记录迁移夹具通过 |
| P1 | 远端错误描述、未知错误码、意外 Web 异常可能回显秘钥 | 只公开安全错误码/状态；未知错误固定化，去除敏感异常链，结果只存白名单并遮蔽当前 token（含嵌套字典键/response id） |
| P1 | 项目内链接可指向被禁止的 `.env`；无 path 的 Git diff 可输出已跟踪秘钥文件 | 同时校验请求路径和解析后的真实路径；Git 先列文件逐个准入，目录 pathspec 拒绝，敏感文件不请求正文 |
| P1 | Git 项目配置的 textconv、external diff、fsmonitor 能触发外部程序；Windows 的 which 还可能优先选择当前目录伪程序 | 只从明确的绝对 PATH 目录选 Git 并固定 argv，禁用上述机制及 pager；相对/空目录被忽略，故意失败的 textconv 不执行 |
| P1 | worker 在 Runtime 根启动 Python，同名 `myth` 包可抢先导入 | 从实际安装源码目录启动；真实子进程 help 测试验证攻击包未执行 |
| P2 | 返回 profile subject 检查存在绕过路径，多 audience 未检查 azp | 始终绑定既有 subject；校验 azp、规范 JWT 编码、RS256 和至少 2048-bit RSA。PyJWT 最低版本升至 2.14.0 |
| P2 | 刷新后权限收窄仍可能使用新 token；短有效期被人为延长 | 刷新后再次检查实际 scope；使用真实 `expires_in`，缺失/畸形寿命拒绝 |
| P2 | 回调重复参数可产生歧义；无关 CLI 请求可提前结束登录 | 安全字段先拒绝重复/超长值，监听器校验 Host 和当前 state；伪造请求不结束合法等待 |
| P2 | 旧账号仍 connected，前端新登录可能提前判定成功 | 公开 login opportunity id/revision 绑定这次完成；清 popup opener，降低外部页面操控工作台的机会 |
| P2 | 无 Origin 的跨站 GET、宽松 Host 解析、半开 HTTP 请求 | 检查 Sec-Fetch-Site 和唯一精确 Host；设置 15 秒 socket 读取等待，拒绝重复 Content-Length/Transfer-Encoding；保留 callback 所需的合法导航 |
| P2 | OAuth/API JSON、SSE 单行和 Git stdout 可先无限累积后截断 | JSON/整次 SSE 8 MiB、SSE 帧 2 MiB；Git 输出至多读取展示上限再停止，文件名单另设上限 |
| P2 | OpenAI/Ollama 明确的 4xx 拒绝被泛化为 UNKNOWN | 发布 FAILED 收据并结算已报告用量；无完成事件、网络中断等仍 UNKNOWN，不自动重试 |
| P2 | 策略资格/活动 baseline 在事务前检查，竞争者可能覆盖新指针；晚到评测可改写 PROMOTED | publish/rollback 在 BEGIN IMMEDIATE 内核对；证据提交在写锁内复核不可变状态；固定交错测试通过 |
| P2 | ObjectStore 摘要可被当作任意路径；模型地址查询可能把秘钥存进设置 | 摘要必须为小写 64 位 SHA256；设置与 provider 拒绝 URL userinfo/query/fragment |
| P3 | 重复目录请求、会话全表查找、Memory 把所有命中正文留到最后 | 公开目录短缓存、过滤索引、全扫描稳定 top-k；性能与返回语义对照见下节 |

### 登录与轮换的实际顺序

```text
begin_login
  -> 内存 state / nonce / verifier，600 秒 TTL，最多 16 个挑战
  -> 自有动态 client 或明确既有 client，exact 127.0.0.1 callback
callback
  -> 唯一字段、state/epoch/issuer/client 绑定
  -> 固定 token endpoint，PKCE exchange
  -> JWKS/RS256/iss/aud/azp/exp/iat/sub/nonce
  -> 系统凭据库保存完整新代次
  -> 非秘钥 profile 元数据标 connected + login_revision
refresh
  -> 同根跨线程/进程锁 + 重读真实凭据
  -> 先保存 refresh_pending
  -> 一次轮换请求
  -> 身份/scope/寿命校验 -> 系统库保存 -> connected
  -> 不明确/崩溃：禁止旧 refresh replay，要求重新登录
logout
  -> 同一锁，先 signed_out + 新 epoch + 清挑战
  -> 尝试远端 revoke
  -> 清理系统库全部受清单追踪的代次（包括未完成写入）
```

元数据、SQLite、浏览器 localStorage、事件和对象仓库均不承担 OAuth token 保存。授权 URL 中仍必须存在一次性 state/nonce/challenge；它们不等于 API/access/refresh/ID token。callback 的 code/state 不进入访问日志，响应设置 no-store/no-referrer。

系统库与元数据是两个系统，没有伪造“同事务”。分块失败可保留完整旧代次或禁用未完成新代次；refresh 的 durable pending 防止旧 token 重用。系统库读写/删除失败保持认证不可用，不能降级为文件。重授权是对轮换结果不明的保守恢复，不能承诺所有网络故障都无感恢复。

远端撤销与本机退出是两个事实；网络不可用时可以本机 signed_out，但不能声称服务端已经撤销。用户输入本身若包含秘钥，仍可能被当作会话/附件数据保存或发送：传输层不会把用户主动贴入正文的任意秘密自动识别为凭据。

## 性能与首 token

用同一 Python 3.13.9、相同合成数据分别加载基线源码和修改后源码；没有真实模型请求。SQL 指标为预热后 9 次中位数，Memory 指标包含 tracemalloc 开销；目录延迟为人为固定 20 ms，仅用来度量重复请求数量。

| 固定夹具 | 基线 | 修改后 | 能说明什么 |
|---|---:|---:|---|
| 1000 会话 / 100000 消息，过滤单会话返回 100 条 | 7.826 ms，SCAN | 0.143 ms，索引 SEARCH | 该夹具下消息过滤约快 55 倍；小库/冷缓存收益不同 |
| 10000 条匹配 Memory，返回 6 条 | Python 峰值 21009577 B | 855326 B | 约少 96% Python 峰值内存；不是整个进程 RSS |
| 同一 Memory 检索耗时 | 296.275 ms | 270.543 ms | 该次测量约少 9%；两版均扫描 10000 条 / 50 页，结果 ID 完全相同 |
| 5 秒内 10 次 Ollama 目录 preflight | 10 次 / 204.555 ms | 1 次 / 20.422 ms | 消除重复目录 I/O；20 ms 是模拟值 |

其他减少开销的修改：bootstrap 复用一次主数据库装配、去掉重复 Goal 查询；搜索在遍历前剪掉 node_modules/私有目录；Git 大 stdout 不再全部积累；Responses 接到 `response.completed` 就返回，不等连接 EOF。

ChatGPT 公开模型目录缓存 30 秒，Ollama preflight 5 秒；只缓存成功的公开结果，返回副本，显式“检查连接”强制刷新。每次 ChatGPT 目录缓存命中前仍从系统库检查凭据、状态、scope 和寿命，logout/login revision 分隔缓存。缓存不会证明服务仍在线，短窗口内服务退出会由实际调用错误正常处理。

OpenAI API Key 和 ChatGPT 路径都请求 stream；供应商调用开始到首个非空 output delta 的本机时间写入 `time_to_first_token_ms`，Observatory 显示最近一次 First token，没有报告显示 N/A。计时包括调用内认证获取/刷新，不包括之前的 Web admission、知识检索和 preflight。

**这个 delta 通常是 JSON 决策的片段，不等于用户看到自然语言的首字。** Runtime 仍只消费完成的 ModelResult；前端没有新增逐 token 回答显示，Ollama 仍使用完整 JSON。不能把流式解析或新增计量说成已经降低真实模型 TTFT。真实改善需要同账号/模型/输入、分冷/热缓存、重复试次实测；OpenAI 的 prompt cache 计量也只采用实际供应商报告，不推测命中。

## 逐模块记录

以下路径相对 `src/myth/`。“核对”表示完成相应静态合同/危险点检查并由全套既有测试覆盖涉及行为；没有新增反例的模块，不等于已经单独完成动态模糊测试。纯声明和 planned 目录不会被当成已实现的执行能力。

| 模块 | 核对重点、修改或剩余边界 |
|---|---|
| `__init__.py` | 按需公开导入、原类身份、版本；README 与实际版本不一致已修复 |
| `acceptance.py` | 固定 acceptance 摘要、证据 coverage、INCONCLUSIVE、必需上下文不足提前拒绝；保持既有合同 |
| `adapters/__init__.py` | 仅包入口，无隐藏 I/O |
| `adapters/agent_execution.py` | 允许文件绑定受管基线，不能重新读取原文件改变验收；read receipt/recover 不重放不确定机会 |
| `adapters/agent_store.py` | Run/预算/初始准入事务、固定请求身份、验收与交付门；已有原子性/恢复测试保留 |
| `adapters/conversation_execution.py` | 链接与敏感路径、搜索分页、Git 程序执行、受管输出；本次重点修复并补安全反例 |
| `adapters/driver_lock.py` | 同 Run 本机线程互斥、释放语义；不是分布式锁 |
| `adapters/personal_store.py` | Goal/进度同事务、旧 Run 不倒写新状态、Trigger 明确授权；跨 restart 测试保留 |
| `adapters/workspace_store.py` | 准入共享连接、固定快照、游标/租约、项目/知识/消息；补查询索引与 URL 约束 |
| `agent_runtime.py` | Exact 装配入口与有界步数/输出；不把模型完成声明当验收 |
| `application/__init__.py` | 纯用例包入口 |
| `application/agent.py` | 原 Run 执行/等待/恢复；已知 provider failure 转 FAILED，保留 UNKNOWN 门 |
| `application/conversation_agent.py` | 安全点 Control、Goal checkpoint、晚到收据；已知 provider failure 分类修正 |
| `artifacts.py` | 原子对象发布、摘要重读、受管文件与收据先行；增加 digest 路径形状校验 |
| `auth/__init__.py` | 自有认证公开接口，未接入 Pi/Codex 凭据 |
| `auth/chatgpt.py` | PKCE/OIDC、系统库、回调/轮换/退出/缓存；本次最大修改，实际 WinVault 与竞争/崩溃反例验证 |
| `auth/transport.py` | 新增无 credential redirect、响应大小、安全错误码及递归脱敏；不修改全局 urllib opener |
| `cli.py` | 显式参数/装配、自有 auth 命令；已安装 wheel 的 CLI/Demo smoke 通过，未执行真实账号登录 |
| `conversation.py` | AST 算术禁止 eval/调用/属性、表达式和指数限制、词面检索与 schema；保留既有反例，知识 query terms 仍逐候选计算 |
| `conversation_context.py` | 当前任务/澄清/附件必留、旧工具折叠带来源、序列化字节预算与 Compact 版本消费；未减少关键上下文来换速度 |
| `conversation_ports.py` | 对话/Control/Memory/Goal checkpoint 的协议边界，无网络执行 |
| `core/__init__.py` | 最小纯合同入口 |
| `core/primitives.py` | Goal 身份/生命周期词汇，不承载 I/O 权限 |
| `decision_runtime.py` | Ticket 前后、模型收据、用量结算、失败缓存与恢复；补已知失败收据，未把 5xx/无 completion 当可重试 |
| `demo.py` | 确定性本机 demo，不是模型质量/真实 OAuth 证据 |
| `domain.py` | 纯状态枚举、摘要、exact patch、错误分类；无文件/网络调用 |
| `domains/__init__.py` | 正交合同导出，不扩大权限 |
| `domains/coordination.py` | 策略成熟度/角色目录；登记不代表并行执行 |
| `domains/information.py` | L0/L1/L2 与增益合同；分辨率不冒充验收质量 |
| `domains/intent.py` | Intent Picker 纯协议 |
| `domains/personal.py` | 显式 Trigger 数据，不按模型输出自动创建权限 |
| `durable_executor.py` | 全局/Run lease、心跳和进度分开、UNKNOWN 不调度；修复 Python 同名包抢先导入，已有 restart/lease 反例保留 |
| `evaluation_runner.py` | 固定 suite 与真实/fixture provider 边界、独立 oracle；未按修复结果挑题 |
| `goal_scheduler.py` | 到期争抢、同请求去重、停机合并、断连延后、固定模型设置；未扩大计划执行权 |
| `models.py` | 供应商无关消息/结果、结构决策与参数解析；原始模型 JSON 不是授权 |
| `platform/__init__.py` | 元数据/合同公开入口 |
| `platform/calibration.py` | 逐题配对、成本事实/缺失、门限；均值不替代证据 |
| `platform/capabilities.py` | EXECUTABLE 与 PLANNED 区分；没有通过本次审查开放 shell 或通用 Python |
| `platform/components.py` | 产品架构/成熟度投影，不代表能力已经执行成功 |
| `platform/context.py` | required 优先、必需项超预算拒绝、保留 dropped 来源；字节不是准确 tokenizer |
| `platform/contracts.py` | 成熟度与职责纯合同 |
| `platform/control.py` | pause/resume/stop/model/thinking/compact 纯修订；命令不撤销已发生效果 |
| `platform/control_store.py` | 写事务分配 revision、终态拒绝控制、Compact 请求固定版本；保留安全点与迟到收据合同 |
| `platform/cost_model.py` | 权重显式登记、同 ID 不可改写；没有推断用户成本偏好 |
| `platform/evaluation.py` | 固定集/配对/完整性门、PASS/FAIL/INCONCLUSIVE；部分集不获得发布资格 |
| `platform/evaluation_store.py` | 评测版本/逐题账本与覆盖，不把替身当真实 provider |
| `platform/evolution.py` | 候选/发布决策纯合同 |
| `platform/evolution_store.py` | publish/rollback/stale baseline/评测不可变；写事务内复核并补两个实际交错反例 |
| `platform/kernel.py` | 组件装配别名，保持兼容身份 |
| `platform/mcp.py` | 发现目录，不实现远端 MCP 调用或凭据；启用真正执行前仍需独立授权/网络审查 |
| `platform/memory.py` | 类型/来源/revision/撤销纯目录，Memory 不授予权限 |
| `platform/memory_store.py` | 可见作用域完整扫描、事实等级、撤销；稳定 top-k 减少内存且保持全部覆盖 |
| `platform/observability.py` | 持久事件投影，不把模型描述当收据 |
| `platform/retrieval.py` | 后端 ready 路由；向量/图声明不代表真实集成 |
| `platform/skills.py` | 纯目录与能力需求，未执行第三方脚本 |
| `platform/subagents.py` | 角色与单角色预算份额纯合同；真正并行分配前需批次总额预留，不能仅依赖各自 fraction |
| `platform/workflow.py` | DAG 引用/循环/ready 纯验证；递归 DFS 的极大图栈深度是启用通用工作流前的剩余边界 |
| `ports.py` | Hexagonal 协议、能力/状态/观察边界；无具体副作用 |
| `providers/__init__.py` | 固定 provider factory、拒绝旧 pi-openai；构造不会发业务模型请求 |
| `providers/base.py` | 统一结构协议 |
| `providers/ollama.py` | 有界 JSON、不跟随重定向、端点拒绝含秘钥参数、4xx 分类/错误脱敏；没有宣称逐 token UI |
| `providers/openai.py` | 正式 OAuth endpoint、TLS、SSE 完成/失败/帧上限、usage 缺失、秘钥脱敏；记录首输出 delta，不等待 EOF |
| `providers/scripted.py` | 确定性 fixture 与独立证据；不会伪装为真实服务 |
| `runtime.py` | Intent/Ticket/效果/收据/settle/verify、受管副本、重启核对；本次未改基础效果状态机 |
| `store.py` | 参数化 SQL、BEGIN IMMEDIATE、预算预留/结算、一次机会/事件顺序；SQLite 原子性不等于外部 exactly-once |
| `strategies/__init__.py` | 明确纯策略导出 |
| `strategies/information_gain.py` | 固定配对证据的增益估计，不把模型自评当收益 |
| `strategies/information_resolution.py` | 同来源固定版本的分辨率选择，不代替验收 |
| `strategies/intent_pick.py` | 保守算术/知识线索、日期/百分号等反例，未擅自调路由门限 |
| `task_benchmark.py` | 每试次持久证据、fixture 与 real 区分、独立字节验收；本次性能脚本不混入模型质量评价 |
| `web.py` | 固定静态资源、Host/Origin、回调日志、下载、JSON/异常边界；补 fetch metadata、读等待及长度头校验 |
| `web_workspace.py` | 事务外 preflight、公开目录短缓存、bootstrap、usage 汇总、控制与下载；长会话仍需要完整 JSON 投影 |
| `workspace.py` | 显式仓储/执行/Control/Memory/Goal 装配，无新增隐式授权 |
| `webui/index.html` | 固定 DOM/本地资源，未嵌入 OAuth 秘钥或 CDN |
| `webui/app.css` | 展示资源，无执行/凭据状态；本次未改布局 |
| `webui/app.js` | 动态内容转义、稳定 request_id/页面代数、登录窗口；修复当前登录机会判定与 opener |
| `webui/inspector.js` | 收据/预算/恢复身份投影，增加真实 First token/N/A；保持第三栏 |
| `webui/goals.js` | 明确计划表单身份、迟到响应隔离、文本转义；计划授权仍由服务端维护 |

### 包装、启动与依赖

- `pyproject.toml`：`PyJWT[crypto]>=2.14.0,<3`；验证环境是 PyJWT 2.14.0、keyring 25.7.0、cryptography 46.0.3。升级只安装在审查虚拟环境，没有改全局 Anaconda。
- `.github/workflows/ci.yml`：保留 Windows/Linux × Python 3.12/3.13，新增完整历史的已知秘钥模式扫描。这里报告的实测是 Windows/Python 3.13.9；其他 CI 组合要看实际 CI 结果。
- `start-myth.ps1`/入口：仍通过显式 CLI 启动 loopback 服务；本次没有安装开机服务、后台监控或改变用户现有账号。
- 系统凭据库必须是直接安全后端，拒绝明文/chainer/fail/null。Linux/macOS 的真实凭据库本次未实测；相同模块名也不构成对被篡改 Python 环境的保护。
- 新增 `audit_secret_patterns.py`、`benchmark_local_overhead.py`、`validate_os_credentials.py`，分别提供不回显秘钥的扫描、固定本地对照、随机 namespace 合成凭据 smoke。

## 复核命令

在审查代码根执行；构建/安装请使用独立虚拟环境。

```powershell
$env:PYTHONPATH='src'
python -m compileall -q src tests scripts
python scripts/check_annotations.py
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
python scripts/audit_secret_patterns.py
python scripts/benchmark_local_overhead.py
python scripts/validate_os_credentials.py           # 只检查后端
python scripts/validate_os_credentials.py --allow-os-store  # 随机合成记录，finally 清理
python -m pip wheel . --no-deps --no-cache-dir --wheel-dir dist
```

对照脚本 `--source <基线源码/src>` 可加载已固定基线；需要完整 git history 才能扫描所有历史。不要从不可确认的复制件读取用户真实凭据。原始本机日志在审查副本 `.runtime/review-evidence/`，不进入 Git 或交付包。

## 尚需真实环境验证 / 后续边界

1. **真实 ChatGPT 完整链路**：账号交互登录、dynamic client 注册、实际 scope、模型列表、一次真实 Responses、正常刷新与撤销。当前签名/HTTP/轮换证据是本机夹具；账户 eligibility 与官方服务合同会变化。
2. **真实端到端性能**：区分用户点击到调用、供应商 TTFT、完成耗时、tokens/s、冷热 prompt cache 与系统库/网络代理开销。当前只修掉可复现的本地开销，新增可观测计量。
3. **长历史/大库**：session API 仍返回完整历史/事件，知识和 Memory 仍全扫描；大规模使用需要游标/增量投影及可验证索引策略，不能通过静默截断重要上下文提速。
4. **并发与环境**：认证串行会在刷新时阻塞同根状态读取；跨根共享同一 profile 未验证。HTTP 有读等待与正文限制，仍不是抗恶意同用户连接洪泛的生产 HTTP 服务。
5. **外部效果与长跑**：保留 UNKNOWN/no-replay、lease/cursor 及 quick soak 反例；本次没有重新做真实模型的 2–3 小时浸泡，也没有验证分布式 worker、通用 shell、远端 MCP 或真实多 Agent 执行。
6. **文件与供应链**：路径过滤保护当前读取合同，不是 OS 文件沙箱，无法排除同用户在检查后替换文件的竞态。环境变量只约束应用的读取方式；进程环境、内存、操作系统和后续依赖更新仍需独立管理。本次不是全部传递依赖/所有历史形式的漏洞证明。

## 对照的官方资料

- 自有 dynamic client、PKCE/OIDC、可选 ID Token hint：[OpenAI Sign in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)。
- 正式 Responses、模型资格与完成事件：[OpenAI Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)。
- 刷新轮换/重放与 OAuth 恢复原则：[RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)；audience/azp：[OpenID Connect Core](https://openid.net/specs/openid-connect-core-1_0.html)。
- Windows CredentialBlob 上限：[Microsoft CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)；实际编码/复制/删除行为：[keyring Windows 后端](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py)。
- PyJWT 非规范签名编码公告，修复版本 2.14.0：[GHSA-hxm8-2xgr-2p9m](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-hxm8-2xgr-2p9m)。Myth 未使用 raw JWT hash 作为撤销身份，不能据该公告推断现有 Myth 可直接绕过退出；本次仍提高依赖基线并显式检查规范编码。
- PyJWK 算法白名单公告：[GHSA-jq35-7prp-9v3f](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-jq35-7prp-9v3f)。Myth 原路径传 `.key` 而非 PyJWK 包装对象、固定 RS256，暴露条件与公告示例不同；没有将版本受影响等同于实测被利用。
- 延迟与缓存边界：[OpenAI latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization)、[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)；Ollama 已知拒绝/流中错误：[Ollama errors](https://docs.ollama.com/api/errors)。
