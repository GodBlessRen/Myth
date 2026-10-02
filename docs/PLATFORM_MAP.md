# Myth v0.6 — Breadth-first Platform Map

这次不再按「做完一小块再想下一块」推进，而是先固定整套平台的最终形状，再逐层把 `wired` 升级为 `usable`。

## 状态语义

- **usable**：已有真实用户路径与测试，当前可以依赖。
- **wired**：接口、状态/数据合同、装配位置和最小行为已经存在，但尚未完整接入产品主链。
- **planned**：只定义边界，不对模型或用户宣称可执行。

## P0 → P1000

| Phase | Layer | 当前 | 下一轮深化 |
| --- | --- | --- | --- |
| P0 | Durable Runtime | usable | 继续把旧 P1/P2 状态迁入事务级端口 |
| P10 | Conversation | usable | Streaming / message branch / richer artifacts |
| P20 | Control Plane | wired | 持久 Command Inbox + steer/pause/resume/abort/model/thinking |
| P30 | Capability Registry | wired | 所有工具通过统一 ToolSpec/authority admission |
| P40 | Context Compiler | wired | 替换 conversation/exact 两套上下文拼装 |
| P50 | Memory | wired | SQLite revisions + Working/Episodic/Semantic/Procedural |
| P60 | Retrieval/RAG | wired | RetrievalPort + lexical baseline + vector/hybrid optional adapters |
| P70 | Workflow | wired | Workflow Run / Step persistence and resumable DAG execution |
| P80 | SubAgent | wired | child Run + parent budget/capability delegation |
| P90 | Skills | wired | skill loader/registry + context injection + capability requirements |
| P100 | MCP | wired | connected server adapter + MCP tool → CapabilitySpec mapping |
| P110 | Observability | wired | Runtime Inspector projections: trace/token/cost/context/tool/recovery |
| P120 | Evaluation | wired | fixed task suites + quality gates + cost reports |
| P130 | Evolution | wired | candidate policy registry + replay/eval + explicit promotion |
| P1000 | Distributed Runtime | planned | only after a real worker/multi-user need exists |

## Product rule

```text
Conversation / UI
        ↓
    MythKernel
        ↓
Control + Context + Memory + Retrieval
        ↓
Decision / Workflow / SubAgent
        ↓
Capability Registry
        ↓
Durable Runtime
Action → Attempt → Ticket → Receipt → Verification → Delivery
        ↓
Observability → Evaluation → Evolution
```

The bottom Runtime remains the authority.  Registry, Skill, MCP, Workflow,
SubAgent, Memory and Evolution layers can propose or organize work; none may
turn discovery metadata into execution permission.

## Breadth-first implementation rule

Every new layer must first satisfy four things:

1. it has a named owner and stable contract;
2. it has a minimal deterministic behavior test;
3. its current maturity is explicit;
4. it cannot bypass the durable Runtime.

Only after the complete skeleton exists do we optimize depth, UI and model behavior.
