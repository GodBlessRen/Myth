# Myth Architecture Constitution

## 0. 一句话

**Myth 固定事实与边界，不固定智能如何组织。**

这条规则优先于具体框架、模型、协议和 Agent 产品形态。

## 1. 稳定 Core

Core 只保留长期不会因为 Agent 形态变化而重写的事实对象：

```text
Goal
  └─ Run
      └─ Action
          └─ Attempt
              ├─ Ticket
              └─ Receipt
                    └─ Artifact
                         └─ Verification
```

- **Goal**：长期意图，可跨多个 Run。
- **Run**：一次可恢复的执行生命周期。
- **Action**：一个稳定的原子意图。
- **Attempt**：Action 的一次实际执行机会。
- **Ticket**：允许 Attempt 开始；不是成功证明。
- **Receipt**：Attempt 实际发生了什么。
- **Artifact**：不可变产物或证据。
- **Verification**：独立判断结果是否满足固定要求。

Conversation、Workflow、SubAgent、MCP、模型供应商都不是 Core。

## 2. 正交 Domains

Domains 是围绕 Core 的同级职责，不构成必须顺序经过的层：

| Domain | 职责 |
| --- | --- |
| Coordination / 统筹 | 选择 Direct / Agent Loop / Workflow / Routing / Parallel / Multi-Agent 等组织方式 |
| Control / 控制 | Steer / Pause / Resume / Stop / 模型与 Thinking 切换 / Compact |
| Execution / 执行 | 把已获准的工作交给具体 Executor，并对账结果 |
| Capability / 能力 | 能力发现、版本、风险和准入 |
| State / 状态 | Run、Budget、Command、Event 与产品事实 |
| Context / 上下文 | 从持久事实生成有预算、有来源的模型投影 |
| Memory / 记忆 | Working / Episodic / Semantic / Procedural 版本化记忆 |
| Personal State / 个人状态 | Goal、Trigger、Preference、Permission、Connected Account 等明确个人状态 |
| Verification / 验证 | 独立验收与交付边界 |
| Observability / 观测 | Trace、Token、Budget、Ticket、Receipt、Recovery 的派生视图 |
| Evaluation / 评测 | 固定测试集上的质量、安全、成本比较 |
| Evolution / 演进 | 只产生候选策略；不能直接改正在运行的 Run |

## 3. Strategy，不升格成 Layer

下面这些是可插拔策略，不是所有请求都必须经过的“层”：

- Decision
- Planning
- Routing
- Scheduling
- Delegation
- Parallelism
- Workflow
- Evaluator-Optimizer
- Multi-Agent
- Managed Agent
- Personal Agent

同一个 Goal 可以按任务选择不同 Strategy。

```text
Direct:        Goal → Run → Answer
Agent Loop:    Goal → Run → Decide ↔ Act ↔ Observe
Workflow:      Goal → Run → A → B → C
Multi-Agent:   Goal → Coordinator → Child Runs
Managed Agent: Goal → AgentPort → Remote Managed Agent
Personal:      Goal ← Trigger → Run ... over time
```

## 4. 六边形边界

Core/Domain 依赖 Port，不依赖具体厂商。

典型 Ports：

- DecisionPort
- ExecutionPort
- MemoryPort
- EventPort
- ApprovalPort
- AgentPort
- ArtifactPort
- ObservabilityPort
- GoalRepository

Adapters 可以随生态变化替换：

- OpenAI / Anthropic / Google / Meta / Ollama
- MCP / A2A
- Browser / Shell / Python / Test
- SQLite / Vector DB
- Chat / Email / Webhook / Timer

**协议和厂商只能进入 Adapter 外圈。**

## 5. Personal Agent 规则

Personal Agent 不是另一套 Runtime。

它是在同一 Core 上增加：

```text
Long-lived Goal
+ Trigger
+ Personal State
+ Scheduler/Event source
+ Permission/Approval
+ Persistent Environment
```

其中：

- Preference / Permission 是显式 Personal State，不靠 Memory 猜。
- Memory 是经历产生的可版本化知识，不授予权限。
- Trigger 可以创建未来 Run，但 Trigger 本身不拥有执行权。
- Background work 仍走 Action → Attempt → Ticket → Receipt。

## 6. Control 规则

产品统一使用：

```text
Steer / Pause / Resume / Stop / Compact
```

**Stop 的含义：停止调度新的工作。**

Stop 不声称已经发出的模型请求、工具调用或外部副作用被物理撤销；晚到结果仍按真实事实记录。

旧的 `abort` API 仅为兼容 v0.8 保留，不再作为新代码和 UI 词汇。

## 7. 成熟度

不再使用 P0/P10/.../P1000 表示架构阶段。

每个 Core/Domain/Strategy/Adapter 独立标记：

- **exists**：合同/边界已存在。
- **connected**：已经接入真实装配或持久化路径。
- **usable**：有真实用户路径与测试，可以依赖。
- **hardened**：经过故障、安全、规模或兼容性强化。
- **planned**：只保留明确边界，不能宣称可用。

开发策略仍然是 **breadth first, depth later**：哪怕未来有很多 Plan，也优先让整体形状和接口存在，再由真实测试决定哪里加深。

## 8. 命名门槛

核心词汇冻结为：

```text
Goal / Run / Action / Attempt / Ticket / Receipt / Artifact / Verification

Coordination / Control / Execution / Capability / State
Context / Memory / Personal State / Observability / Evaluation / Evolution

Port / Adapter / Strategy
```

新增 Engine、Manager、Plane、Capsule、Supervisor、Coordinator 等抽象前，必须证明现有词无法准确表达。

简单词优先。
