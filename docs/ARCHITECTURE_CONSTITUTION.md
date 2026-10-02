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

## 4. Intent Pick 与 Information

### Intent Pick

Intent Pick 不是传统单标签分类器，也不是固定 LLM 调用。

它回答的是：

> **当前输入最值得走哪条处理路径？**

允许的实现包括规则、关键词、Jev、Small Model、Embedding、LLM 或级联。Intent Pick 只选择处理路径，不授予执行权限。

典型 Route：

- `direct`
- `local_retrieval`
- `deterministic`
- `agent`
- `ask_user`

当前状态：**connected**。保守规则已进入 Turn admission：严格算术可走 deterministic；显式/强匹配本地资料可走 local_retrieval；其他输入稳定回退 Agent Loop。

### Information Resolution / 信息分辨率

Information Resolution 描述**同一份信息的表示细腻程度**，不是“答案够不够”。

```text
L0  Abstract
    极低成本摘要 / retrieval representation

L1  Overview
    导航、结构、关系、rerank representation

L2  Detail / Evidence
    细节、原始证据、source-of-truth representation
```

原则是 Progressive Disclosure：先看低分辨率信息，只有任务需要时才升级 L0 → L1 → L2。

当前状态：**connected**。Knowledge 支持固定 source/digest 的 L0/L1/L2 projection；Turn admission 使用 durable Active Policy 选择 Resolution，并把 policy identity 固定进 snapshot。

### Information Delta / 信息增量

Information Delta 是**信息状态前后发生了什么变化**：

- added
- updated
- removed
- conflicted

它是变化事实，不代表变化一定有价值。

当前状态：**exists**。Delta 数据合同已存在；尚未形成自动 Memory/State lifecycle delta pipeline。

### Information Gain / 信息增益

Information Gain 是：

> **在已有信息状态下，继续获取/展开某份信息能给当前任务带来多少边际价值。**

高相似不等于高增益；重复信息即使语义接近，边际 Gain 也可能接近 0。

后续选择可以考虑：

```text
Expected Information Gain
-------------------------
Token / Latency / Tool Cost
```

但当前不会伪造一个“科学”的互信息数字。Estimator 必须明确自己的语义、训练/统计来源和适用范围。

当前状态：**connected（offline evidence）**。Gain 只从同 suite/version、同 case 的 paired EvalObservation 推导；成本默认保持向量，只有显式 Cost Model 才计算 gain-per-cost。它不直接控制 live admission，也不能自动 Promote policy。

## 5. 六边形边界

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
- IntentPickPort
- InformationResolutionPort
- InformationGainPort
- InformationDeltaPort

Adapters 可以随生态变化替换：

- OpenAI / Anthropic / Google / Meta / Ollama
- MCP / A2A
- Browser / Shell / Python / Test
- SQLite / Vector DB
- Chat / Email / Webhook / Timer

**协议和厂商只能进入 Adapter 外圈。**

## 6. Personal Agent 规则

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

## 7. Observability 规则

Runtime Observatory 是产品合同，不是可选 Debug UI。

必须能从 durable facts 投影：

- Goal；
- Execution Flow；
- Trajectory；
- Token Window；
- Context Window；
- Tool Calls；
- Control；
- Budget。

Observability 只读事实，不拥有业务状态；UI 可以折叠细节，不能伪造或删除核心事实类别。

## 8. Control 规则

产品统一使用：

```text
Steer / Pause / Resume / Stop / Compact
```

**Stop 的含义：停止调度新的工作。**

Stop 不声称已经发出的模型请求、工具调用或外部副作用被物理撤销；晚到结果仍按真实事实记录。

旧的 `abort` API 仅为兼容 v0.8 保留，不再作为新代码和 UI 词汇。

## 9. 成熟度

不再使用 P0/P10/.../P1000 表示架构阶段。

每个 Core/Domain/Strategy/Adapter 独立标记：

- **exists**：合同/边界已存在。
- **connected**：已经接入真实装配或持久化路径。
- **usable**：有真实用户路径与测试，可以依赖。
- **hardened**：经过故障、安全、规模或兼容性强化。
- **planned**：只保留明确边界，不能宣称可用。

开发策略改为 **真实任务优先，按失败加深**：已有抽象先接受真实任务、故障与评测检验；没有真实瓶颈，不继续横向扩张 Layer / Strategy / Protocol。

## 10. 命名门槛

核心词汇冻结为：

```text
Goal / Run / Action / Attempt / Ticket / Receipt / Artifact / Verification

Coordination / Control / Execution / Capability / State
Context / Memory / Personal State / Observability / Evaluation / Evolution

Port / Adapter / Strategy

Intent Pick / Information Resolution / Information Delta / Information Gain
```

新增 Engine、Manager、Plane、Capsule、Supervisor、Coordinator 等抽象前，必须证明现有词无法准确表达。

简单词优先。
