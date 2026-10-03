# Runtime Observatory Contract

Runtime Observatory 是 Myth 主工作台的**第三栏**，不是可选 Debug Panel。

目标只有一个：

> 用户能从第一个 Prompt 一直追到最终 Artifact，知道系统看到了什么、调用了什么、花了多少、现在卡在哪里，以及完成声明有什么证据。

## 必须常驻的事实

### Goal

显示：

- goal_id / title；
- current_state；
- progress_note；
- next_action；
- waiting_for；
- revision；
- last_run_id。

Goal 只是工作上下文，不能扩大权限。

### Execution Flow

至少能看见当前执行链中的主要阶段：

```text
Intent / Retrieval / Resolution
        -> Model
        -> Tool
        -> Verify
        -> Persist
```

Flow 是对 durable facts 的投影，不创建新的执行真相。

### Recovery

必须显示：

- current step；
- last durable checkpoint；
- current phase；
- recovery state；
- Durable Executor active / stale、PID 与 heartbeat age；
- Driver active / detached / expired；
- lease generation / remaining time（适用时）；
- last durable progress age；
- suspected no progress（只作为观察信号）；
- 下一步是 RESUME 还是 RECONCILE。

必须区分：

```text
INTERRUPTED -> RESUME
UNKNOWN     -> RECONCILE
```

页面刷新、浏览器断开或 Web 进程退出不能把 Run 事实抹掉，也不能停止独立 Durable Executor。执行器 heartbeat 只能证明 worker 进程活着；业务进度必须来自 Execution Cursor / durable events。若 heartbeat 正常但 checkpoint 长时间不变化，UI 标记 `suspected no progress`，不得仅凭时间自动 replay 已发 Ticket。

### Trajectory

按顺序展示 durable events，例如：

- ConversationTurnStarted；
- ModelTicketGranted；
- ConversationContextCompiled；
- ModelAttemptSettled / Failed；
- ConversationToolTicket；
- ConversationToolRecorded；
- RouteFallback；
- ConversationAnswered；
- WAITING / UNKNOWN / recovery 相关事件。

必须保留顺序与事件身份；UI 可折叠，事实不能消失。

### Token Window

至少显示：

- configured context window；
- settled input tokens；
- settled output tokens；
- Prompt Cache hit：命中 token / input token 与命中率（Provider 提供时）；
- model calls；
- unknown-held token liability（存在时）。

不要把 byte budget 冒充 token usage，也不要把 keep-alive、KV cache、相似上下文或推测值冒充 Prompt Cache hit。Provider 不提供缓存计量时必须显示 N/A。

### Context Window

至少显示：

- bytes used / max bytes；
- 当前使用百分比；
- `num_ctx`（provider 管理时明确标识）；
- selected items；
- folded items；
- dropped items。

用户必须能回答：

> 为什么模型没有看到某段信息？

### Tool Calls

至少显示：

- capability；
- operation / ticket identity；
- state；
- result / artifact；
- error；
- approval / authority 状态（存在时）。

模型描述“我调用了工具”不算证据；以 durable operation / receipt 为准。

### Control

显示当前 revision 与：

- Steer；
- Pause；
- Resume；
- Stop；
- Model switch；
- Thinking switch；
- Compact。

### Budget

显示 Runtime 已知预算事实：

- model_calls；
- input_tokens；
- output_tokens；
- tool_calls；
- write_bytes；
- reserved / settled / unknown-held（适用时）。

## 状态语义

必须区分：

- RUNNING
- WAITING_USER
- PAUSED
- INTERRUPTED / RESUME
- UNKNOWN / RECONCILE
- SUCCEEDED / COMPLETED
- FAILED
- BUDGET_EXHAUSTED
- CANCELLED
UNKNOWN 不能被染成普通失败，也不能自动视作可重试。INTERRUPTED 也不能被误标为 UNKNOWN；只有存在已发 Ticket / 未知外部效果时才进入 UNKNOWN。

## UI 原则

1. **摘要常驻，细节渐进展开**
   - 第三栏保持可扫描；
   - 长 payload / 参数 / evidence 按需展开。

2. **事实优先于装饰**
   - 不用动画制造“正在思考”的假进度；
   - 不展示源码中不存在的 Receipt / Verification。

3. **状态色有语义**
   - 橙：运行 / 当前切点；
   - 绿：durable positive state；
   - 红：明确失败 / blocker；
   - UNKNOWN 使用独立中性色/琥珀语义，不与 FAILED 混淆。

4. **第三栏不能因“产品化”被删除**
   - 可在窄屏折叠；
   - 桌面主工作台必须可访问；
   - UI regression tests 应锁定核心 surface identity。

## 数据来源

Runtime Observatory 只投影现有事实：

- Turn Snapshot；
- Event log；
- Control projection；
- Budget accounts；
- Operations；
- Model invocation usage；
- Goal work state；
- Context report；
- Artifact / Receipt / Verification。

Observatory 不拥有状态，不写业务真相。

定时创建的 Run 在 Goal 区显示 `GoalWakeupAdmitted` 的 schedule ID 和 due time。桌面保持第三栏；窄屏通过顶部 Runtime 按钮打开同一面板，保留 Goal、Flow、Recovery、Trajectory、Tokens/Cache、Context、Tools、Control、Budget。

## 验收问题

任何 UI 改动完成后，至少能回答：

1. 当前 Goal 是什么？
2. 现在执行到哪一步？最后 durable checkpoint 在哪？
3. 最近发生了哪些 durable event？
4. 当前上下文用了多少？哪些被 dropped/folded？
5. Token 使用、Prompt Cache 命中率和 unknown-held 是多少？
6. 调用了哪些 Tool？Ticket/Operation 状态是什么？
7. 当前 Control / Budget 是什么？
8. Driver 如果此刻消失，应该 RESUME 还是 RECONCILE？
9. “完成”基于什么 Artifact / Receipt / Verification？

答不上来，就不是合格的 Runtime Observatory。


## Durable Executor / Progress Watch

长任务把三种“活着”严格分开：

```text
Executor heartbeat  -> 独立 worker 进程仍持有全局短租约
Driver heartbeat    -> 某个 Run 当前有负责人
Durable progress    -> Execution Cursor / Event 的 checkpoint 实际推进
```

因此“worker 心跳正常”绝不等价于“任务正在有效前进”。默认观察阈值到达后只报告 **suspected no progress**；如果当前存在 UNKNOWN/TICKETED 外部效果，仍必须先 RECONCILE。这个规则用于发现“线程还活着但执行卡死”的情况，同时避免把看门狗变成重复调用制造器。


## Worked Time / Model Wall

Myth 把两种时间分开显示：

- Assistant 回复旁的 `用时 Xm Ys`：从本轮用户输入持久化到对应 Assistant 回复持久化的整轮 wall-clock。
- Runtime Observatory 的 `Model wall`：Runtime 围绕每次 `provider.invoke` 实测并聚合的调用 wall-clock。

两者都不是“模型内部纯推理时间”。前者包含工具、Runtime、排队和网络；后者只覆盖 provider 调用边界，但仍可能包含网络与供应商排队。若供应商报告内部 duration，应作为第三类独立 metric 保留。

运行中的“用时”由服务端持久消息起点投影，每次会话轮询刷新；页面刷新不会重置计时。
