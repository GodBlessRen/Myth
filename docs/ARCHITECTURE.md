# Myth Architecture

> 稳定边界：[ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md)  
> 组件地图：[PLATFORM_MAP.md](PLATFORM_MAP.md)  
> 运行观测：[OBSERVABILITY.md](OBSERVABILITY.md)

## 1. 一句话

Myth 是一个单机 modular monolith：用 durable Runtime 保存执行事实，用 Goal-first work loop 推进长期工作，用 Ports / Adapters 隔离模型、工具和基础设施。

## 2. Runtime shape

稳定 Core：

```text
Goal -> Run -> Action -> Attempt -> Ticket -> Receipt -> Artifact -> Verification
```

Core 固定：

- durable identity；
- authority；
- effect fact；
- immutable evidence；
- verification boundary。

Coordination / Control / Execution / Capability / State / Context / Memory / Personal State / Observability / Evaluation / Evolution 是正交 Domain。

Intent Pick、Information Resolution、Direct、Agent Loop、Workflow、Routing、Parallel、Multi-Agent 等属于 Strategy，不是固定执行层。

## 3. Golden path — Conversation / Goal

```text
User message
  -> Session / optional Goal admission
  -> frozen Turn Snapshot
     - settings
     - project scope
     - Goal checkpoint
     - retrieval evidence
     - Intent Pick
     - Information Resolution policy
  -> bounded Context compilation
  -> Model Ticket
  -> model decision
  -> local validation
  -> optional Tool Ticket
  -> tool effect / Receipt
  -> next Step
  -> reply / ask_user / failure
  -> Goal checkpoint
```

Goal work state包含：

- current_state；
- progress_note；
- next_action；
- waiting_for；
- last_run_id；
- revision。

下一 Session 继续同一 Goal 时，新的 Turn 读取当前 Goal work state 并**冻结副本**。后续 Goal 更新不会倒写历史 Turn。

## 4. Authority boundary

模型、Memory、Goal、Context 都是数据。

只有本地 Runtime 能授予执行权：

```text
Decision proposal
  -> capability admission
  -> budget reservation
  -> Ticket
  -> effect
  -> Receipt
  -> settlement / verification
```

模型自述“已执行”不能代替 Receipt。

### 4.1 Delegation / Sub-Agent

第一版 Multi-Agent 不增加新 Core，也不把 Supervisor 固定成必经层。父模型在正常 Agent Loop 中自行判断是否调用 `agent.delegate`：

```text
Parent decision
  -> optional agent.delegate
  -> explicit task + bounded context + admitted source refs
  -> isolated read-only model worker
  -> contracted result
  -> Parent continues normal Agent Loop
```

隔离 worker 不继承完整父历史、Memory 或工具目录，不可写入、调用工具、再次委派或向用户提问。它的结果作为 Observation 回到父步骤；不是 Receipt 的替代物，也不自动通过 Acceptance。委派模型调用继续使用父 Run 的 durable model Ticket / receipt / budget 账本，因此恢复和成本仍可观测。

## 5. Interruption / recovery

Run 生命周期不绑定 Browser、HTTP request 或 Web Driver 生命周期。

Conversation / Goal 的已准入工作由独立 **Durable Executor** 驱动。Web 启动时只确保本机执行器存在；之后关闭页面、刷新页面或 Web 进程退出都不会主动停止该执行器。执行器竞争自己的全局短租约，再对每个 Run 继续竞争既有 Driver Lease，因此多个进程不能把同一个 Run 当成两项工作执行。机器重启后再次启动 Myth 时，过期租约允许新执行器从原 Run 的 durable cursor 接管，而不是创建替代 Run。

Conversation Run 额外保存：

- durable Execution Cursor；
- current phase；
- last durable checkpoint；
- recovery state；
- Driver Lease / generation / heartbeat。

Driver heartbeat 丢失时：

```text
no uncertain external effect
  -> INTERRUPTED
  -> RESUME from durable checkpoint

Ticket / provider call outcome uncertain
  -> UNKNOWN
  -> RECONCILE before replay
```

Lease 只是“谁当前负责驱动”的事实，不是执行成功证明。新的 Driver 只能在租约失效后接管，并仍要经过 normal recovery gate。

## 6. UNKNOWN semantics

SQLite 事务只能保证数据库自身原子性，不能把 provider / filesystem 等外部效果宣称为 exactly-once。

Ticket 后结果不明：

```text
known success   -> settle
known failure   -> FAILED
unknown outcome -> UNKNOWN / unknown-held
```

UNKNOWN 先 reconcile，不盲目重发。

Provider 明确返回 context truncation 属于已知失败，不冒充 UNKNOWN。

## 7. Context

Conversation context 是从 durable facts 生成的 bounded projection，不是执行记录本身。

### 7.1 Live Information Control

Agent Loop 中现有读取/检索工具同时构成一个 bounded information loop：

```text
LLM identifies an information need
        ↓
SEEK / EXPAND proposal
        ↓
Information Control admission
   - novelty
   - pagination progress
   - total/action/source budget
        ↓
normal Runtime Tool Ticket / Receipt
        ↓
Observation returns to Context
        ↓
next model decision
        ↓
KEEP when no more information action is needed
```

Controller 是纯策略：不执行 I/O、不调用模型、不拥有新的持久表。它只从当前 Turn 已持久的 activities 重建消费状态，因此进程退出/恢复不会重置信息预算。拒绝发生在 Tool Ticket 前，属于已知准入失败，不制造 UNKNOWN，也不消耗一次真实 tool call。

第一版故意不把 offline Information Gain 数字接入 live admission；先用可验证的 novelty / progress / boundedness 建立稳定控制面，再由固定 Eval 证明后决定是否让 Gain 影响排序或升级。

Conversation context 是从 durable facts 生成的 bounded projection，不是执行记录本身。

优先级包括：

- 当前任务；
- Goal checkpoint；
- project/control instructions；
- pinned attachments；
- latest tool result；
- retrieved Knowledge；
- recalled Memory；
- older history / previews。

Ollama projection budget 与 `num_ctx` 对齐；远端 provider 使用本地 projection cap。Context report 记录：

- selected；
- folded；
- dropped；
- byte usage；
- `num_ctx`；
- control revision。

完整 durable history 不因 Compact / folding 被删除。

### 7.2 Context Anchor / 增量压缩

长会话不会把所有旧消息持续塞回模型窗口。Turn 准入时，旧消息按稳定序号增量合并为 **Context Anchor**，最近尾部继续保留原文：

```text
durable workspace_messages
        ↓
previous Context Anchor + newly aged messages
        ↓ deterministic extractive merge
bounded Context Anchor + recent verbatim tail
        ↓
ContextCompiler
```

Context Anchor 是有损派生投影，不是 Memory、权限或验证事实；它保存 covered message count、lineage digest 与自身 digest。极小窗口可以丢弃 Anchor，不能为了保留摘要挤掉当前任务、项目指令或固定来源。完整原始消息始终保存在 durable store。

## 8. Retrieval / Memory

Knowledge：

- local UTF-8 documents；
- chunked lexical baseline；
- shared / project scope；
- stable candidate pagination；
- source + digest provenance；
- L0 / L1 / L2 fixed-source projection。

Memory：

- Working / Episodic / Semantic / Procedural；
- revision / provenance / revoke；
- global / project / session scope；
- `fact_level=context` 不自动升级为 verified fact。

Retrieval / Memory 都不能授予执行权限。

### 8.1 Progressive Tool Disclosure

Conversation Tool Catalog 超过阈值后不再把所有工具 schema 永久塞进 Prompt。默认只暴露常用能力和 `tool.search / tool.describe`：

```text
small visible catalog
   ↓
tool.search / tool.describe
   ↓ durable Observation
   ↓
next model step sees discovered tool
   ↓
normal Capability admission -> Ticket -> Receipt
```

Discovery 只改变**下一模型步骤的可见目录**，不授予执行权限。远端模型即使猜中隐藏 capability，也会在 Ticket 前被本地 Runtime 拒绝；一次被拒绝的“偷调”不会自动解锁该工具。

## 9. Control

产品术语：

```text
Steer / Pause / Resume / Stop / Model Switch / Thinking Switch / Compact
```

Stop 表示“不再调度新的工作”。

它不宣称已经发出的 provider/tool effect 被撤销。晚到结果仍按真实事实记录。

### 9.1 Structured Failure Observation + Verify-on-Stop

已知参数、权限、合同、Information Control 等失败统一投影为结构化 Observation：

```text
category / code / capability / retryable / expected / hint
```

同时保留兼容的人类 `error` 文本。这个 Observation 发生在已知拒绝路径，不制造 Tool Receipt，也不把已知失败升级成 UNKNOWN。

Conversation 的 `request_completion` 先经过 **Completion Guard**。模型仍列出 `remaining`、引用不存在的 evidence，或最近一次已执行 verifier 未通过时，停止请求会被退回为结构化 Observation，父 Loop 必须继续。Guard 不自己执行测试、不修改 Acceptance；没有已执行 verifier 时也不会伪造验证事实。

## 10. Exact verification path

Exact-mode 是独立 use case，不把普通聊天的 COMPLETED 冒充语义验收。

固定 acceptance manifest 后：

```text
baseline
 -> exact candidate effect
 -> durable receipt
 -> independent verifier
 -> immutable accepted Artifact
 -> delivery
```

模型的 completion request 只是 claim。

## 11. Evaluation / Evolution

Evaluation 使用固定 versioned suite：

```text
EvalSuite
 -> Runner
 -> Observation
 -> Report
 -> Release Gate
```

Policy release：

```text
full baseline suite
 + full candidate suite
 -> paired evidence
 -> calibration gate
 -> ELIGIBLE
 -> explicit Promote
 -> Active Policy for future Turns
```

partial-suite eval 只能研究，不能发布。

Evolution 不自动 Promote，也不能修改正在运行或历史 Turn。

## 12. Ports / Adapters

依赖方向：

```text
CLI / Web
   ↓
Workspace / AgentRuntime
   ↓
Application use cases
   ↓
Ports / domain contracts
   ↑
SQLite / local execution / providers
```

协议与厂商只能进入 Adapter 外圈。

认证同样属于 Adapter 边界：

- OpenAI API Key 只从环境变量读取；
- Sign in with ChatGPT 由 Myth 自己实现 OAuth authorization-code + PKCE/OIDC；
- OAuth secret 只进入系统安全凭据库，不进入 Runtime SQLite / Event / Artifact / Web JSON；
- OAuth registration/profile metadata 与 Runtime execution state 分离；
- Myth 不读取 Pi/Codex auth files，也不复用其他应用的 OAuth client identity。

登录挑战只在内存中存活十分钟，退出会更新非秘钥 login epoch 取消旧挑战。认证聚合的登录、刷新、选择与退出共用线程/进程锁；刷新派发前保存 `refresh_pending`，崩溃或结果不明时必须重新授权，不能重发旧 refresh token。系统凭据库的分块清单先登记新代次、最后切换 active，旧代次及未完成代次可清理；SQLite 不承担凭据事务。

传输拒绝 credential redirect，OIDC 使用固定 issuer/JWKS、RS256、至少 2048-bit RSA、规范 compact JWT、audience/azp/nonce/subject 校验。授权 URL 不包含可选 ID Token。公开模型目录可短时缓存，每次仍复核实际系统凭据和授予 scope；缓存不授予权限。

Responses 只在 `response.completed` 后发布完整结果。`time_to_first_token_ms` 是供应商调用开始到首个非空输出 delta 的本机计时，可能包含认证刷新，JSON 决策 delta 不等于页面首字；没有 delta 时显示 N/A。已知拒绝进入 FAILED，传输中断仍保持 UNKNOWN / RECONCILE。细节与验证范围见 [安全与性能审查](SECURITY_PERFORMANCE_AUDIT.md)。

Core 不依赖：

- OpenAI；
- Ollama；
- MCP；
- A2A；
- Browser；
- Shell；
- SQLite。

## 13. Persistence

主要 durable categories：

- Run / Action / Attempt；
- Ticket / Receipt / budgets / events；
- Conversation Session / Turn / Step / messages；
- Execution Cursor / Driver Lease / heartbeat；
- projects / documents / chunks；
- Memory；
- Goal / Goal work state / Trigger / Personal State；
- Goal schedule / due occurrence / immutable model settings；
- Evaluation runs / observations；
- Cost Model / Policy Candidate / Active Policy / history；
- content-addressed objects / Artifact evidence。

Schema 以 additive migration 为主；旧 active-run upgrade 需要单独验证，不能靠 `CREATE TABLE IF NOT EXISTS` 自动宣称兼容。

## 14. Web boundary

本地 Web 是 loopback-only single-user workspace，不是多用户安全边界。

页面只投影 Runtime facts：

```text
History / Context | Conversation / Task | Runtime Observatory
```

第三栏必须保持 Goal / Flow / Recovery / Trajectory / Tokens / Cache Hit / Context / Tools / Control / Budget 可观察。执行器心跳与业务进度分开：`executor heartbeat` 只证明 worker 活着，`Execution Cursor.updated_at` 才作为最近 durable progress 的观察信号；长时间无 checkpoint 只能标记为 **suspected no progress**，不能据此盲目重试未知外部效果。

## 15. 本地 Goal Wake-up

`GoalScheduler` 是现有 Workspace 的本地适配器，不增加 Core 层次。用户显式创建一次性或固定间隔计划；独立 Durable Executor 默认每两秒检查 due schedule，provider readiness 在事务外检查。Web 只负责确保执行器已启动和展示其心跳，不再拥有计划任务的生命周期。

同一 SQLite 事务提交 occurrence、Turn/Run、Goal link 和 admission checkpoint。`request_id` 固定计划入口身份；`(schedule_id, sequence)` 唯一约束固定每次工作机会。未来 due time 仅在 admission 成功时推进，停机期间的过期重复时段合并为一次。

提交后 Driver 消失时，原 Run 从 Execution Cursor 进入正常恢复流程；不创建替代 Run。UNKNOWN、PAUSED、WAITING_USER 不由定时器自动重放。会话与 Goal 的未完成轮次阻止新 admission；旧 Run 的迟到 Goal checkpoint 不能覆盖新 Run。

详见 [GOAL_WAKEUP.md](GOAL_WAKEUP.md)。

断连等待归 Workspace/Goal 仓储，使用持久失败次数及 UTC 截止时间，间隔为 1/2/4/8/16/32/60 秒。供应商只报告派发前错误证据，DecisionRuntime 结算零用量失败后才释放当前请求键；未知效果不自动重发。后台线程按原 Run/step 接续，浏览器读取独立重连。详见 [NETWORK_RECOVERY.md](NETWORK_RECOVERY.md)。

## 16. 当前明确不做

当前没有：

- 任意 shell / arbitrary code executor；
- 操作系统级开机自启动/服务管理器与通用事件触发；当前 Durable Executor 是本机独立进程，由 Myth 启动并用 SQLite lease 自恢复；
- 分布式 lease / worker；
- 多用户 auth；
- 通用 MCP/A2A production integration；
- 语义上“万能”的 completion verifier。

这些由真实任务需求决定是否进入下一阶段。

## 17. 状态所有权与原子准入

个人状态仓储拥有 Goal/进度/关联写入；对话仓储协调 Turn admission，通过个人仓储加入同连接活动事务，不能复制对方写表逻辑。计划机会加入同一事务，初始进度缺失也在这个事务内补齐。

独立精确文件入口先在事务外准备摘要对象及私有基线，再把 Run/账号/Action/Attempt/预留/事件一起提交；失败不留下只有 Run 的新入口。未引用私有准备不具有 Ticket，也不代表已修改原项目。

应用对 Control、Memory 和 Goal checkpoint 依赖明确端口；Exact/Conversation 共用独立本机 Run 锁，不互相实例化业务执行器。包入口按需导出，纯领域冷导入不加载数据库/认证/供应商依赖。

当前仍保留 Control 对 Core/对话表的跨聚合写入，以及回答、记忆、长期进度和 Driver 清理的分别提交。目录和端口分离不等于全面状态隔离；文件、凭据库与数据库也不是一个事务。详细协作表与剩余耦合见 [CODE_GUIDE.md](CODE_GUIDE.md)。
