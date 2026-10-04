# Myth Architecture Constitution

## 0. 一句话

**Myth 固定事实与边界，不固定智能如何组织。**

这条规则优先于具体框架、模型、协议和 Agent 产品形态。

Myth 的架构同时受四条同等重要的基本原则约束：

- **关注点分离（Separation of Concerns）**：不同职责拥有明确边界和状态所有者；一个关注点的变化应尽量局部化，不能要求无关模块共同修改。
- **解耦（Decoupling）**：Core / Domain 依赖稳定语义和 Port，不依赖具体供应商、协议、数据库、UI 或进程实现。
- **原子性（Atomicity）**：一个业务决定必须有明确提交边界；不能把部分成功伪装成完整成功。
- **六边形架构（Hexagonal Architecture）**：业务语义位于内圈，外部世界通过 Port / Adapter 接入；协议和厂商不得反向塑造 Core。

这四条原则不是互相替代的风格偏好，而是共同约束模块职责、依赖方向、状态所有权与修改半径的架构宪法。

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

## 2.1 Evidence Before Score / 证据先于分数

Evaluation 的分数只是证据的压缩投影，不是证据本身。

- 任何质量结论都必须能回溯到固定 Case、Run/Execution、Verification/Final State 与 Grader/Oracle 身份。
- 能由代码和最终状态确定的判定优先使用 deterministic oracle；未校准的模型 Judge 不得作为发布事实。
- 重复试次必须区分 **pass@k（至少一次成功，Capability）** 与 **pass^k（k 次全部成功，Reliability）**；平均成功率不能替代可靠性。
- 成本比较优先报告 **cost per successful outcome**；失败试次的成本不能从分母中消失。
- 缺测、样本不足和不确定性保持显式；不得把小样本波动直接包装为 Champion、Policy 增益或发布证据。
- Evaluation 只提供证据与资格。SOTA Route 负责发现，Evolution 负责证明和显式发布；任一单次漂亮 Run 都不能直接改变生产策略。
- Historical Replay 只能在同一冻结比较条件下重放“历史真实出现过的边”；未观察分支必须保持 `UNOBSERVED`，Replay 结果不能直接产生 `ELIGIBLE`、授权或 Promote。
## 2.2 Context、执行与评测的不变量

效率优化只能减少**无效工作**，不能偷偷降低权限、证据、可恢复性或验收标准。

- **State ≠ Context**：持久事实是 source of truth；模型 Context 只是 State 的有预算投影。投影折叠、Compact、UI 隐藏都不能删除原始事实。
- **Context = Projection(State)**：成本与节约优先按 provider-visible projection 计量；raw history 很大不代表真实请求仍然很大。无法量测的节约保持 N/A，不得补造。
- **失败回原路径**：Observation fold、摘要、Compact、Action Fusion 等效率路径失败时，必须优先保留原始证据/原始可执行路径，而不是让效率改进本身造成信息丢失。
- **摘要必须绑定来源**：LLM/小模型生成的摘要、Reduction、Compaction 都只是候选；可确定校验的关键事实必须绑定 source digest / exact quote / Artifact / Receipt / Verification。
- **Deterministic successor**：Runtime 能确定执行、验证、恢复或计价的工作，不再浪费一次 LLM 决策；只有中间无需新语义判断的后继才允许融合。
- **Partial success is explicit**：mutation 成功而 fused verifier/projection 失败时分别记录，不把部分成功伪装为“什么都没发生”。
- **成本要算未来请求**：cache rewrite、compaction、delegation、index/retrieval 等可以有 upfront cost / outstanding debt；是否执行应看剩余请求能否回本，而不是只看单次 Token。
- **Hysteresis**：自适应优化需要 cooldown / margin / emergency override，防止 compact/route/delegate 在相邻步骤振荡。
- **Representation transition ≠ semantic transition**：Compact、Memory consolidation、reconnect、branch reconstruction、UI projection 不得凭空制造 Goal progress、Action completion 或 Verification。
- **Capability 可达性必须可观测**：enabled 不等于 reachable。Capability 的 available / exposed / reachable，以及未生效原因必须有稳定 reason code。
- **Capability floor first**：任何效率候选先守住固定能力/安全下限，再比较 Pareto 成本；最终 held-out 结果不得反馈回候选搜索。
- **Sub-Agent 只共享必要来源**：默认共享显式 evidence/source refs 与有界 task/context，不复制完整父聊天历史或“所有想法”。

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

### Delegation / Sub-Agent 不变量

Myth 对 Multi-Agent 的稳定定义是 **Context Isolation + Contracted Return**，不是“Agent 越多越聪明”。

- 是否委派属于父 LLM 的 Strategy 选择；Runtime 不增加强制 Multi-Agent 层，也不靠固定分类器替模型决定。
- Child 只得到父级显式传入的 task、bounded context 与已准入 source refs；完整父对话、Memory 与工具目录不会自动继承。
- Child 权限不得超过父级。当前 `agent.delegate` 只连接一个 read-only isolated worker：无工具、无写入、无用户交互、无递归委派。
- Child 返回 summary / coverage / evidence refs / remaining 等合同结果；工作轨迹不回灌父 Context。
- Child 输出属于 Observation，不是 Verification。最终工具执行、证据核对、验收与交付仍由父 Agent / Runtime 负责。
- 委派本身消耗父 Run 的模型与工具预算，并使用稳定 request identity；已发出但结果不明时继续遵守 UNKNOWN / RECONCILE。

当前状态：**connected**。Conversation Agent 已把 `agent.delegate` 暴露为可选能力，是否调用由当前主模型自行判断；第一版刻意保持单层、只读、可观测。

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

### Live Information Control / 实时信息控制

实时信息控制把 Progressive Disclosure 接入正在运行的 Agent Loop，但不增加新的执行层或另一套 Tool。

稳定动作只有：

```text
KEEP    当前信息足够，继续推理/执行/回答
SEEK    寻找新的候选来源或导航范围
EXPAND  展开已知来源的更多细节/证据
```

当前实现把既有 `knowledge.search / memory.search / project.search / project.list` 视为 SEEK，把 `knowledge.resolve / knowledge.read / memory.timeline / memory.resolve / project.read` 视为 EXPAND。LLM 只提出信息需求；Context 侧策略在 Tool Ticket 前执行准入，Runtime 仍负责真正的 Ticket / Receipt / Budget。

第一版坚持四个不变量：

- **Novelty**：同一 Run 内已经结算的精确信息请求不能重复派发；
- **Progress**：分页必须沿 `next_cursor / next_offset` 前进，已耗尽视图不能继续假装获取新信息；
- **Bounded**：实时信息动作有全局、SEEK / EXPAND 和单来源上限，并始终至少给最终非信息步骤保留机会；
- **Observable**：每次已准入 SEEK / EXPAND 将小型控制投影保存在现有 activity 结果中；恢复和 UI 从 durable facts 重建，不依赖进程内计数器。

`KEEP` 不产生工具调用；当模型不再申请信息工具而继续任务时即成立。Offline Information Gain 目前只作为评测/未来策略证据，不直接控制线上准入，避免未经充分校准的分数成为 Runtime 真理。

当前状态：**connected（bounded-live-v1）**。

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
- TextEmbeddingPort
- VectorIndexPort

向量数据库必须保持**派生索引语义**：权威正文、作用域、revision、archive/revoke 与事实等级继续由所属状态仓储拥有；Vector hit 必须回权威源 hydration。Milvus 等 Adapter 不得因为相似度更高而升级事实、权限或 Verification。

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

## 11. 简体中文指导性注释

注释是项目的工程合同。新增、修改和重构代码必须同步维护简体中文指导性注释；标识符、协议字段和外部标准术语保持其原始拼写。

逐行审阅代码，对具有设计含义的声明、协作点、状态变化和关键步骤给出指导。注释必须帮助后续开发者解释代码、定位故障和安全修改，而不是只有功能名称。

- **文件开头**：说明架构位置、职责、上下游、状态所有者、允许的 I/O，以及这个文件不应承担的职责。
- **类和协议**：说明实例生命周期、协作对象、依赖方向、可替换边界和并发约束；纯数据合同说明不可变性与身份语义。
- **函数和方法**：说明输入前提、输出含义、关键副作用、调用顺序、幂等身份、异常含义和恢复入口。端口说明调用方与实现方各自的责任。
- **属性、字段和关键变量**：说明含义、单位、来源、版本、作用域及所有权；区分事实、投影、缓存、凭证和验收结论。
- **关键步骤**：标明校验、准入、事务提交、外部派发、收据、结算、核对和验收的边界，以及中途退出后依据哪些持久事实恢复。
- **条件和异常分支**：解释为什么允许、拒绝、等待或转入 UNKNOWN；不得把已知拒绝写成效果不明。
- **测试和维护脚本**：说明所证明的不变量、故障注入点和证据边界；替身通过不能表述为真实供应商成功。
- **前端与启动配置**：说明状态来源、渲染/事件协作、请求去重、生命周期与响应式边界；不得把 UI 状态当作执行事实。

注释应紧邻对应代码，随实现一起更新。旧设计描述进入历史归档；当前代码旁不得留下已失效的版本说明。注释不能代替可执行约束和测试。

## 12. 关注点分离、解耦、原子性与六边形检查

- **关注点分离**：每个模块应有一个清晰主要职责和明确状态所有者。业务决策、持久化、供应商协议、认证、观测、UI 投影、评测与演进不能因为实现方便而揉进同一模块；一个关注点变化时，应优先让修改停留在自己的模块、Port 或 Adapter 内。
- **修改半径检查**：新增或修改一个供应商、UI 展示、存储实现、认证方式或 Strategy 时，如果必须同时修改多个无关 Domain 或 Core 对象，应先判断是否发生关注点泄漏。
- **六边形依赖方向**：应用用例依赖领域和端口；具体数据库、供应商、网络、文件、UI 和进程操作在适配器或装配入口实现。外圈可以依赖内圈，内圈不能依赖外圈。
- 一个状态聚合只由其仓储修改。跨聚合的准入不变量由明确的事务协调入口提交，不依赖调用方重复拼装 SQL。
- 原子操作是一个不可部分提交的业务决定。注释必须明确事务内包含哪些事实、事务外发生哪些效果。
- SQLite 只保证本地数据库事务。对象文件和外部供应商采用稳定身份、不可变证据及核对协议，不能宣称跨系统 exactly-once。
- 投影、认证和观测不能偷偷取得业务状态写入权；共享一条连接不意味着每个模块都可以修改别人的表。
- 清理前确认实际引用和恢复用途。历史设计、诊断脚本、固定旧评测集归档；活跃回归测试、迁移、收据和兼容合同按真实使用证据判断。
