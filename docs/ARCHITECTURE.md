# Myth 当前架构

Myth 是面向个人工作的本地 Agent Runtime：长期 Goal 保存工作意图，一次 Run 保存可恢复执行身份；策略可以替换，权限、预算、Ticket、Receipt 与验收事实不能绕过。

规范见 [架构宪法](ARCHITECTURE_CONSTITUTION.md)，具体源码入口见 [CODE_GUIDE](CODE_GUIDE.md)。本页负责全局关系，功能细节由下方专题维护。

## 从入口到效果

```text
Web / CLI / 到期计划
  → Workspace / AgentRuntime 装配与准入
  → application 中的 ConversationAgent / AgentDriver
  → Repository / Execution / Control 等端口
  → SQLite 仓储、模型供应商、受管文件和测试进程适配器
```

内圈保存领域合同与纯策略；外圈负责 HTTP、认证、SQL、文件和供应商协议。`runtime.py`、`workspace.py` 是装配/协调入口，不以目录名假装全项目已经完全解耦。

## 状态由谁拥有

| 事实 | 写入所有者 | 主要约束 |
| --- | --- | --- |
| Core Run、账号、事件与执行栅栏 | `RuntimeStore` | 同事务身份/预算核对；栅栏只递增 |
| 模型机会、请求键、决定 | `DecisionRuntime` | 固定请求对象 → 模型 Ticket → 收据 → 结算 |
| Session、Turn、工具机会、执行游标 | `SqliteWorkspaceRepository` | 当前步骤只消费一次；晚到收据不能重开终态 |
| 控制命令与快照 | `SqliteControlService` | 命令排序由自身 revision 拥有；状态投影交给对应仓储 |
| Goal、个人状态、工作进度 | `SqlitePersonalState` | 创建即含初始进度；`last_run_id` 拒绝迟到旧轮次覆盖 |
| 文档、分片与知识检索 | `SqliteKnowledgeRepository` | 原文按 digest 固定；共享/项目范围由权威记录核对 |
| Memory、Evidence、revision | Memory 仓储 | 上下文事实等级与来源显式；不授予工具权限 |
| 派生知识视图、页面树 | `SqliteKnowledgeViews` | 来源版本/水位校验；自身输出不循环作为来源 |
| 收尾义务、交付验收、工作项 | Delivery 仓储 | 义务持久化；验收绑定 subject digest |

共享 SQLite 连接不等于共享写权限。跨聚合业务入口让各所有者加入同连接的 `transaction_scope`；外部连接或非活动事务明确拒绝。

## 一次工作怎样推进

1. 准入事务核对入口身份、Session/Goal 占用，保存 Run、预算、Turn、用户消息、冻结快照和游标。相同身份重试复用事实，冲突内容拒绝。
2. Driver 取得本机 Run 锁并维护租约；恢复旧机会后，才复用决定或创建新模型请求。心跳表示存活，持久游标表示进度。
3. 模型输出是提案。工具范围、参数、Capability 和预算通过后生成 Ticket，外部效果在短事务之外执行。
4. 先发布收据，再在数据库结算。效果与用量分别核对；无收据且无法证明未派发时保持 UNKNOWN。
5. 回答提交前保存 finalization 义务；Memory 与 Goal 收尾按义务幂等补偿。回答结束、长期 Goal 完成、验收通过分别显示。

`agent.delegate` 先准入父工具，再准入子模型。子模型已完成而父工具尚未留收据时，恢复从固定子决定补收据；恢复入口不持有 Provider，不再次联网。无子模型 Ticket 可闭合为未启动；未决模型机会继续 UNKNOWN。

模型池在 Turn 设置中冻结 1 主 + 最多 3 子配置。用户档位是初值，主模型可选槽位并给能力判断；`pool-v2` 从已结算意见校准同类路由，不训练模型或修改策略代码。`DelegationCoordinator` 固定交接合同，子 Repository/Execution/Control 视图复用同一 `ConversationAgent` 与 Context 编译器；子检查点由父仓储按 CAS 写入对象/事件，外部调用和输入工具仍记同一父 Run 账本。正文、公开元数据不可变保存，默认摘要与回读页是投影。内容采用和元数据审核分别记录，拒收仍记费用并要求替代结果；模型意见不修改独立 Verification。当前串行单层，配置、计价和恢复边界见 [模型池](MODEL_POOL.md)。

## 控制的原子边界

命令和安全点均在同一写事务读取当前状态。Control 只写自己的表，Turn/Core/Goal 由对应所有者加入；后半段 SQL 失败，命令、设置、投影与事件一起回滚。每条命令返回自己提交的 revision。

- Pause 阻止后续驱动；Resume 重新允许驱动，但执行前仍核对旧机会。
- WAITING_USER 保留问题身份，Resume 不代替回答。终态 Turn 不接受新控制，也不被迟到 gate 覆盖。
- Stop 不声称撤销已派发请求；真实晚到结果照常记录。
- 模型/推理档位在事务外查询能力，提交时 CAS 核对控制 revision，拒绝过时检查结果。
- Compact 按实际模型请求使用的控制 revision 消费；命令序号不能覆盖 Core 的独立执行栅栏。

## State 与 Context

State 是持久事实，Context 是有预算的投影。Observation 可折叠并精确回读；Compact seed 绑定持久证据。知识使用 `knowledge.search → knowledge.resolve` 的 L0/L1/L2；L1 分片、L2 字符游标各自有明确单位和限额。分页不改变来源 digest。

Memory 与派生知识视图的版本/撤销/刷新协议见 [MEMORY_LIFECYCLE](MEMORY_LIFECYCLE.md)。可选 Milvus 只提供候选，必须回 SQLite 核对 scope、digest/revision 和 archive/revoke；失效时报告降级，见 [MILVUS_RETRIEVAL](MILVUS_RETRIEVAL.md)。工具发现只改变后续可见目录，不直接授权执行。

## 专题与验证

| 主题 | 当前合同 |
| --- | --- |
| 跨会话工作与到期调度 | [GOAL_WAKEUP](GOAL_WAKEUP.md)、[LONG_RUN_VALIDATION](LONG_RUN_VALIDATION.md) |
| 网络中断与零派发重试 | [NETWORK_RECOVERY](NETWORK_RECOVERY.md) |
| 收尾、验收、受信测试 | [DELIVERY](DELIVERY.md)、[SECURITY](../SECURITY.md) |
| 执行过程、预算与成本展示 | [OBSERVABILITY](OBSERVABILITY.md)、[SESSION_STATISTICS](SESSION_STATISTICS.md) |
| 固定任务、完整分母与策略证据 | [TASK_BENCHMARK](TASK_BENCHMARK.md)、[SOTA_ROUTE](SOTA_ROUTE.md) |
| 当前检查与本轮证据 | [VALIDATION](VALIDATION.md)、[REFINEMENT_REVIEW](REFINEMENT_REVIEW.md) |

Evaluation 的 partial 运行没有发布资格；候选只在完整固定集合与能力下限通过后参与比较，仍需显式 Promote。Historical Replay 只覆盖已观察分支，不产生执行授权。

当前保留单进程/本机服务边界与单数据库格式，不保留无人使用的迁移链。Workspace 仓储、Web 服务仍是较大的协调聚合；后续拆分以真实改动压力为依据，并保住原子准入与恢复入口。下一阶段见 [ROADMAP](ROADMAP.md)。
