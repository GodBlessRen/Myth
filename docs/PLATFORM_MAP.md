# Myth v0.12 — Composable Runtime Map

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
| Coordination | usable | Direct + Agent Loop；strict arithmetic Intent Pick 已接 deterministic 快路；其他组织方式可插拔 |
| Control | usable | Steer / Pause / Resume / Stop / Model / Thinking / Compact；revision 跨连接原子分配 |
| Execution | usable | Model、文件、检索、Diff、Git 只读执行与对账 |
| Capability | usable | Registry + executable/planned 准入 |
| State | usable | SQLite durable state / budget / event / command |
| Context | usable | ContextCompiler + fixed byte budget + fixed-digest Knowledge L0/L1/L2 projection |
| Memory | usable | typed revision + search/revoke + scoped episodic auto-write + full visible candidate scan + provenance fact_level |
| Personal State | connected | Goal / Trigger / explicit state 持久化与 API |
| Observability | usable | Runtime Inspector + operation/event/control projection |
| Evaluation | exists | 固定 Case/Observation/Verdict 合同 + foundation-v1 suite；尚未成为完整在线 eval pipeline |
| Evolution | exists | candidate/promotion contract 存在，不自动发布 |

## Strategies

Strategy 是 Coordination 的可替换策略，不是 Layer。

| Strategy | 当前 |
| --- | --- |
| Intent Pick | connected |
| Information Resolution | exists |
| Information Gain | exists |
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
| Intent Pick | connected (narrow) | strict bounded arithmetic 已在主请求入口走 deterministic 0-model fast path；其他输入稳定回退 Agent Loop |
| Information Resolution | exists + partial connection | L0 Abstract → L1 Overview → L2 Detail/Evidence；Knowledge 已可沿固定 document/digest 分页展开 L2，通用 L0/L1 views 尚未物化 |
| Information Delta | exists | added / updated / removed / conflicted 的状态变化合同；尚未自动接入 Memory lifecycle |
| Information Gain | exists | 边际任务价值及 gain-per-cost 合同；尚无校准 estimator |

