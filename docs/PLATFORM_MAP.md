# Myth Platform Map

Myth 的正式结构是：

```text
                    Core
 Goal / Run / Action / Attempt / Ticket
 Receipt / Artifact / Verification
          ↙          ↓          ↘
       Domains    Strategies     Ports
          ↘          ↓          ↙
                  Adapters
```

## Core

| Core | 当前 | 含义 |
| --- | --- | --- |
| Goal | usable | 长期意图 + durable work state，可跨 Session 继续 |
| Run | usable | 可恢复执行生命周期 |
| Action | usable | 稳定原子意图 |
| Attempt | usable | Action 的一次执行机会 |
| Ticket | usable | effect 开始前的 durable authority |
| Receipt | usable | 实际执行事实 |
| Artifact | usable | 不可变产物 / evidence |
| Verification | usable | 独立验收边界 |

## Domains

| Domain | 当前 | 真实能力 |
| --- | --- | --- |
| Coordination | usable | Direct / Agent Loop + conservative Intent Pick |
| Control | usable | Steer / Pause / Resume / Stop / Model / Thinking / Compact |
| Execution | usable | Model、文件、检索、Diff、Git 只读能力及对账 |
| Capability | usable | Registry + admission |
| State | usable | SQLite durable state / budget / event / command |
| Context | usable | bounded projection + provider-aware context budget |
| Memory | usable | typed revision / scope / provenance / recall |
| Personal State | usable | Goal work state / explicit schedule / atomic wakeup admission / explicit state persistence |
| Observability | usable | 第三栏 Goal / Flow / Trajectory / Tokens / Context / Tools / Control / Budget |
| Evaluation | usable | fixed suites / Runner / Ledger / release evidence |
| Evolution | usable | Cost Model / Candidate / Promote / Rollback；不自动发布 |

## Strategies

| Strategy | 当前 |
| --- | --- |
| Intent Pick | connected |
| Information Resolution | connected |
| Information Gain | connected, offline evidence |
| Direct | usable |
| Agent Loop | usable |
| Workflow | connected |
| Routing | exists |
| Parallel | exists |
| Multi-Agent | exists |
| Managed Agent | exists |
| Personal Agent | connected |

Strategy 不升格成 Layer。真实任务没有暴露需求时，不继续横向深化。

## Adapters

| Adapter | 当前 |
| --- | --- |
| SQLite | usable |
| Local Files | usable |
| Ollama | usable |
| OpenAI API Key | connected |
| Sign in with ChatGPT | usable | Myth-owned PKCE/OIDC + secure OS credential store；不依赖 Pi/Codex auth |
| MCP | exists |
| A2A | planned |
| Browser | planned |
| bounded Test | planned |
| arbitrary Shell | intentionally unavailable |
| Timer / Schedule | planned minimal wake-up |

## 六边形边界

```text
Inbound Adapter
(Chat / future Timer)
       ↓
Application / Domain
       ↓
      Ports
       ↓
Outbound Adapters
(Model / Tool / DB / future MCP)
```

发现能力不等于获得权限；外部系统只能通过 Port / admission 进入。

## 成熟度

- `exists`：合同/边界存在；
- `connected`：进入真实装配或持久路径；
- `usable`：有真实用户路径与 regression tests；
- `hardened`：经过故障 / 安全 / 规模强化；
- `planned`：只保留方向，不能宣称可用。

当前开发策略：

> **真实任务优先，按失败加深。**

不是先铺更多形状。
