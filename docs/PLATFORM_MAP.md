# Myth v0.15 — Composable Runtime Map

Myth 不再把架构描述成 P0 → P1000 的固定层级。

正式结构是：

```text
                Core
 Goal / Run / Action / Attempt
 Ticket / Receipt / Artifact / Verification
          ↙      ↓      ↘
      Domains  Strategies  Ports
          ↘      ↓      ↙
              Adapters
```

## Core

Core 固定事实与权限边界，不固定智能如何组织。

| Core | 当前成熟度 | 含义 |
| --- | --- | --- |
| Goal | connected | 长期意图已持久化；尚未自动调度后台 Run |
| Run | usable | 可恢复执行生命周期 |
| Action | usable | 原子业务意图 |
| Attempt | usable | Action 的一次执行机会 |
| Ticket | usable | 开始执行的持久授权 |
| Receipt | usable | 执行事实 |
| Artifact | usable | 不可变产物/证据 |
| Verification | usable | 独立验收边界 |

## Domains

Domains 是同级职责，不是必须顺序经过的层。

| Domain | 当前成熟度 | 当前真实能力 |
| --- | --- | --- |
| Coordination | usable | Direct + Agent Loop；Intent Pick 已接 deterministic + conservative local_retrieval；其他组织方式可插拔 |
| Control | usable | Steer / Pause / Resume / Stop / Model / Thinking / Compact；revision 跨连接原子分配 |
| Execution | usable | Model、文件、检索、Diff、Git 只读执行与对账 |
| Capability | usable | Registry + executable/planned 准入 |
| State | usable | SQLite durable state / budget / event / command |
| Context | usable | ContextCompiler + fixed byte budget + fixed-digest Knowledge L0/L1/L2 projection |
| Memory | usable | typed revision + search/revoke + scoped episodic auto-write + full visible candidate scan + provenance fact_level |
| Personal State | connected | Goal / Trigger / explicit state 持久化与 API |
| Observability | usable | Runtime Inspector + operation/event/control projection |
| Evaluation | usable | foundation-v1/v2/v3 + executable Runner + durable Eval Ledger + complete-suite release evidence + paired comparison |
| Evolution | usable | Cost Model Registry + Calibration Matrix + durable Candidate Registry + explicit Promote/Rollback + Active Policy revision；不自动发布 |

## Strategies

Strategy 是 Coordination 的可替换策略，不是 Layer。

| Strategy | 当前 |
| --- | --- |
| Intent Pick | connected |
| Information Resolution | connected |
| Information Gain | connected |
| Direct | usable |
| Agent Loop | usable |
| Workflow | connected |
| Routing | exists |
| Parallel | exists |
| Multi-Agent | exists |
| Managed Agent | exists |
| Personal Agent | exists |

以后出现新的 Agent 形态，优先新增 Strategy/Adapter，而不是修改 Core。

## Adapters

| Adapter | 当前 |
| --- | --- |
| SQLite | usable |
| Local Files | usable |
| Ollama | usable |
| OpenAI | connected |
| Pi OAuth | connected |
| MCP | exists |
| A2A | planned |
| Browser | planned |
| Shell | planned |
| Timer / Webhook | planned |

MCP/A2A/模型厂商/浏览器/数据库都不能进入 Core。

## 六边形规则

```text
Inbound Adapter
(Chat / Timer / Webhook / Email)
             │
             ▼
      Application / Domain
             │
           Ports
             │
             ▼
Outbound Adapters
(Model / Tool / MCP / A2A / DB / Browser)
```

外部系统只能通过 Port 进入；发现一个 Tool/Agent 不等于拥有执行权限。

## 成熟度

- `exists`：合同存在；
- `connected`：接入真实装配/持久化；
- `usable`：真实路径 + 测试可依赖；
- `hardened`：经过更强故障/安全/规模验证；
- `planned`：只定义边界。

开发策略：**breadth first, depth later**。先让完整形状存在，再由测试、真实场景和瓶颈决定加深顺序。


## Information concepts

这些不是新的强制 Layer。

| Concept | 当前 | 含义 |
| --- | --- | --- |
| Intent Pick | connected | strict arithmetic 走 deterministic；显式/强匹配本地资料走 conservative local_retrieval；其余回退 Agent Loop |
| Information Resolution | connected | Turn admission 从 durable Active Policy 构造 rule/fixed controller 并固定 policy_id；Promote/Rollback 仅影响未来 Turn |
| Information Delta | exists | added / updated / removed / conflicted 的状态变化合同；尚未自动接入 Memory lifecycle |
| Information Gain | connected | paired fixed-case observed quality delta + cross-case Calibration Matrix；显式 Cost Model 后可计算 gain-per-cost |

