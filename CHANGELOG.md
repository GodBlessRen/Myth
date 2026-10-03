# Changelog

## v0.22 — Detached Durable Executor

- Conversation / Goal 的已准入长任务改由独立 Durable Executor 驱动，Web 只负责确保 worker 存在；关闭页面或 Web 进程不再主动停止任务。
- worker 使用 SQLite 全局短租约；每个 Run 继续复用既有 Driver Lease / generation / heartbeat，同一个 `run_id` 在租约过期后从 durable Execution Cursor 接管，不创建替代 Run。
- 普通 Turn 与 Goal Wake-up 共用同一恢复路径；`UNKNOWN / RECONCILE` 永不自动派发，避免 ambiguous provider/tool effect 被重复执行。
- Runtime Observatory 新增 Executor heartbeat、last durable progress 与 suspected no-progress；明确区分“worker 活着 / Driver 活着 / checkpoint 真正推进”。
- 新增独立 worker CLI：`myth --root <root> worker`；Web 启动时可自动拉起 detached worker。当前仍不是操作系统级开机服务，也不是分布式 worker。
- 增加 Web 生命周期外同 Run 恢复、UNKNOWN no-replay、Goal due admission 与 heartbeat-not-progress 回归测试。

## v0.21.1 — 中文工程指导与准入原子性

- 宪法强制简体中文指导性注释；生产源码、前端、测试与维护脚本补职责/协作/字段/恢复说明，CI 增加说明覆盖守卫。
- Goal 与初始进度共同创建；对话/计划的个人状态写入通过所有者加入同连接准入事务，旧进度缺失不嵌套提交。
- 独立精确文件入口的 Run/账号/Action/Attempt/预留一起提交，准备或资源失败不留下空 Run。
- 两条应用共用独立本机锁；公开入口按需导出，保留旧类身份；同摘要对象发布失败仅在核对完全一致字节后复用。
- 旧固定评测和诊断工具归档；删除重复 Goal 绑定、三处无用导入及可重建旧包镜像；历史回归/迁移/收据保留。
- 完整审阅、清理清单和验证范围见 [ANNOTATION_AUDIT_V0211.md](docs/archive/ANNOTATION_AUDIT_V0211.md)。

## v0.21 — Goal Wake-up and Measured Daily Tasks

- 增加显式一次性 Timer / 固定间隔计划，模型设置在创建时固定，Web 服务每两秒检查到期工作。
- 计划请求去重；Wakeup / Turn / Goal link / admission checkpoint 共用事务；两个连接不能重复认领同一次机会。
- 停机错过的重复时段合并为一次；会话/Goal 忙、暂停、等待或断连时保留计划并延后检查。
- 提交后 Driver 中断由原 Run 恢复；UNKNOWN 不自动重放；旧 Goal checkpoint 不覆盖新 Run。
- 增加「目标与计划」工作台；窄屏 Runtime 入口保留全部观测事实，修复 390px 对话溢出。
- `task-benchmark` 保存 10 个固定日常任务 × 重复试次 × Myth/simple-loop 的完整数据库和独立字节验收；替身与真实 provider 分开标记。
- 真实任务暴露的 PatchContractError 改为 Ticket 前已知拒绝，模型可纠正；补齐步数耗尽及未决收据的 Goal checkpoint。
- CI 扩为 Windows/Linux × Python 3.12/3.13；具体实测边界见 docs/archive/VALIDATION_V021.md。

## v0.20 — Recovery-first Agent Runtime

- Conversation Run 新增 durable Execution Cursor：step / phase / checkpoint / recovery state。
- Web Driver 改为 durable Lease + heartbeat，不再只依赖进程内 `active=set()`。
- Driver 消失且没有不确定外部效果时进入 `INTERRUPTED / RESUME`。
- 已发 Ticket / provider 调用结果不明时保持 `UNKNOWN / RECONCILE`，不盲目 replay。
- 新 Driver 在 lease 失效后接管，并重新经过 normal recovery gate。
- Runtime Observatory 新增 Recovery 区，显示 checkpoint、phase、Driver 与 lease。
- Session UI 标记“可恢复 / 需核对”，支持“从断点继续”。
- 增加跨 Runtime restart、lease expiry、safe resume、UNKNOWN no-replay 回归测试。


## v0.19 — Native Sign in with ChatGPT

- 移除 Myth 对 Pi OAuth / Pi CLI 的认证依赖。
- 按 OpenAI OSS Sign in with ChatGPT 合同实现动态 client registration、PKCE S256、state、OIDC nonce 与 exact loopback callback。
- ID token 验证 signature / issuer / audience / expiry / nonce；返回 client_id 与注册身份绑定。
- access / refresh / ID token 只进入系统安全凭据库；无明文凭据文件 fallback。
- refresh token rotation 跨线程/进程串行；logout 尝试远端 revoke 并始终清除本地凭据。
- ChatGPT plan Responses 使用 `store:false + stream:true`，只在 `response.completed` 后确认成功。
- Web/CLI 新增 login / status / logout；callback query 不进入本地日志。
- 旧 `pi-openai` 设置迁移为 `chatgpt`，旧 durable Run 会收到明确迁移错误。


## v0.18.1 — Cache Observability

- OpenAI Responses 的 provider-reported cached input tokens 写入 durable model usage。
- Runtime Observatory 的 Tokens 区显示 Prompt Cache hit token 与命中率。
- Provider 不提供缓存计量时明确显示 N/A，不从 keep-alive / KV cache / 相似上下文推测。
- cache hit rate 定义为 `cached_input_tokens / input_tokens`。

Myth 只记录已经落地并进入主线的高价值变化。详细提交历史以 Git 为准。

## v0.18 — Goal-first Personal Work Loop

- 长期 Goal 增加 durable work state：
  `current_state / progress_note / next_action / waiting_for / last_run / revision`。
- Conversation 在真实终态写 Goal checkpoint。
- 同一 Goal 可跨 Session / restart 继续，并把 checkpoint 固定进新 Turn Snapshot。
- 第三栏 Runtime Observatory 固定保留：
  Goal / Execution Flow / Trajectory / Tokens / Context / Tools / Control / Budget。
- UI observability identity 加入回归测试。

## v0.17 — Provider Context Hardening

- ModelRequest 增加 `num_ctx` / temperature。
- Ollama 显式传递 `num_ctx` / temperature / keep_alive。
- Ollama 本地 Context budget 从 `num_ctx - output - reserve` 推导。
- provider-confirmed context truncation 记录为 durable FAILED，而非 UNKNOWN。
- ambiguous post-Ticket transport failure 继续保持 UNKNOWN。

## v0.16 — Intent Correctness

- 收紧 deterministic arithmetic grammar。
- 日期 / 版本 / 分数 / 百分比 / 电话形状默认回退 Agent。
- strong / weak knowledge cue 分级。
- calculator rejection 写入 `RouteFallback` 后安全回退。
- foundation-v4 增加 36 条 Intent adversarial cases。

## v0.15 — Evidence-driven Evolution Control Plane

- versioned Cost Model Registry。
- Gain Calibration Matrix。
- durable Policy Candidate Registry。
- complete-suite release evidence。
- explicit Promote / Rollback。
- Active Policy 只影响未来 Turn，历史 Turn 不倒写。

## v0.14 — Paired Evaluation + Information Gain

- Eval Ledger 持久化。
- baseline / candidate paired comparison。
- Information Gain 只从同 case 的 paired Verdict evidence 估计。
- 成本默认保留为向量，显式权重后才计算 gain-per-cost。

## v0.13 — Executable Evaluation + Conservative Routing

- 固定 EvalSuite -> Runner -> Observation -> Report -> Release Gate。
- `myth eval` CLI。
- conservative `local_retrieval` route。
- L0 / L1 / L2 Information Resolution 接入 Turn admission。

## v0.12 — Retrieval Correctness Foundation

- Knowledge 去掉 rank 前 10,000 chunk 静默截断。
- Memory 去掉最近 500 条隐式 recall 上限。
- candidate coverage diagnostics。
- project.search cursor / max_files。
- fixed-digest L0 / L1 / L2 knowledge resolution。
- foundation-v1。

## v0.11 — Runtime Closure

- Control revision 跨 SQLite 连接原子分配。
- Goal admission 与 request identity 绑定。
- scoped Episodic Memory。
- `knowledge.read`。
- bounded deterministic arithmetic fast path。

## v0.10 — Context Continuity

- ContextCompiler 与 bounded projection。
- context selected / folded / dropped evidence。
- Compact / Pause 连续性加强。

## v0.9 — Core / Domains / Strategies

- 从固定“层级栈”重构为：
  Core + Domains + Strategies + Ports / Adapters。
- Goal / Trigger / Personal State 进入持久化边界。
- Stop 成为产品术语。

## v0.8 — Product Control

- Steer / Pause / Resume / Stop。
- Model / Thinking switch。
- Compact。
- durable Memory revision。
- project.search / diff.preview / git.status / git.diff。

## v0.7 — Agent Workbench UI

- 三栏工作台。
- Runtime Inspector / Execution Spine。
- 暖纸张 / 墨色 / 克制橙视觉系统。

## Earlier

v0.1–v0.6 主要完成 Durable Runtime、exact verification、conversation workspace 与 breadth-first platform skeleton。需要逐提交考古时直接查看 Git history。
