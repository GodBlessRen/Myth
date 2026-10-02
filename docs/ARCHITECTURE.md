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

## 5. UNKNOWN / recovery

SQLite 事务只能保证数据库自身原子性，不能把 provider / filesystem 等外部效果宣称为 exactly-once。

Ticket 后结果不明：

```text
known success   -> settle
known failure   -> FAILED
unknown outcome -> UNKNOWN / unknown-held
```

UNKNOWN 先 reconcile，不盲目重发。

Provider 明确返回 context truncation 属于已知失败，不冒充 UNKNOWN。

## 6. Context

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

## 7. Retrieval / Memory

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

## 8. Control

产品术语：

```text
Steer / Pause / Resume / Stop / Model Switch / Thinking Switch / Compact
```

Stop 表示“不再调度新的工作”。

它不宣称已经发出的 provider/tool effect 被撤销。晚到结果仍按真实事实记录。

## 9. Exact verification path

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

## 10. Evaluation / Evolution

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

## 11. Ports / Adapters

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

Core 不依赖：

- OpenAI；
- Ollama；
- MCP；
- A2A；
- Browser；
- Shell；
- SQLite。

## 12. Persistence

主要 durable categories：

- Run / Action / Attempt；
- Ticket / Receipt / budgets / events；
- Conversation Session / Turn / Step / messages；
- projects / documents / chunks；
- Memory；
- Goal / Goal work state / Trigger / Personal State；
- Evaluation runs / observations；
- Cost Model / Policy Candidate / Active Policy / history；
- content-addressed objects / Artifact evidence。

Schema 以 additive migration 为主；旧 active-run upgrade 需要单独验证，不能靠 `CREATE TABLE IF NOT EXISTS` 自动宣称兼容。

## 13. Web boundary

本地 Web 是 loopback-only single-user workspace，不是多用户安全边界。

页面只投影 Runtime facts：

```text
History / Context | Conversation / Task | Runtime Observatory
```

第三栏必须保持 Goal / Flow / Trajectory / Tokens / Context / Tools / Control / Budget 可观察。

## 14. 当前明确不做

当前没有：

- 任意 shell / arbitrary code executor；
- 后台 autonomous scheduler；
- 分布式 lease / worker；
- 多用户 auth；
- 通用 MCP/A2A production integration；
- 语义上“万能”的 completion verifier。

这些由真实任务需求决定是否进入下一阶段。
