# Myth Product Design

## Product identity

Myth 是一个 **Agent Workbench / Personal Work Runtime**。

主界面不是营销 Hero，也不是“知识库 + AI 聊天框”，而是一个持续工作的三栏工作台：

```text
History / Context | Conversation / Task | Runtime Observatory
```

核心体验：

> 工作在中间发生，执行事实在右侧持续可见。

## Visual system

### Color

- Paper `#F6F2EA` — application canvas；
- Surface `#FCFAF6` — composer / panel；
- Ink `#25231F` — primary structure；
- Muted `#7C756A` — secondary facts；
- Signal Orange `#C77732` — running / selected execution cut-point；
- Success `#5E7A63` — durable positive state。

橙色不是装饰色。Runtime state 才能获得强调。

### Type

- System Sans：navigation / conversation / controls；
- Georgia / Noto Serif SC fallback：major title；
- Monospace：ID / token / budget / machine facts。

## Information architecture

左栏：

- Sessions；
- Projects；
- Knowledge；
- secondary context。

中栏：

- Goal-bound Conversation；
- Task；
- Artifact / result；
- user decision。

右栏：

- Goal；
- Execution Flow；
- Trajectory；
- Tokens；
- Context Window；
- Tool Calls；
- Control；
- Budget。

详细观测语义见 [OBSERVABILITY.md](OBSERVABILITY.md)。

## Signature move — Runtime Observatory

过去的 Execution Spine 已扩展成完整 Runtime Observatory。

它的目标不是“显示 Agent 很忙”，而是显示因果：

```text
Goal
  ↓
Intent / Context
  ↓
Model / Decision
  ↓
Authority / Ticket
  ↓
Tool / Effect
  ↓
Receipt / Artifact
  ↓
Verification / Completion
```

只有源码/Runtime 暴露的事实才能显示。

不要伪造：

- Ticket；
- Receipt；
- Verification；
- Token；
- progress。

## Density

第三栏采用：

> **摘要常驻 + 细节渐进展开**

允许折叠 payload，不允许删除事实类别。

桌面必须能访问 Runtime Observatory；窄屏可以折叠为 drawer / secondary surface，不能永久隐藏。

## State design

必须视觉区分：

- idle；
- RUNNING；
- WAITING_USER；
- PAUSED；
- COMPLETED / SUCCEEDED；
- FAILED；
- BUDGET_EXHAUSTED；
- CANCELLED；
- UNKNOWN / RECONCILE。

UNKNOWN 不与 FAILED 共用语义。

## UI discipline

- 不堆相同 card；
- 不用装饰动画模拟执行进度；
- 重要状态文字 + 图形共同表达，不只靠颜色；
- IDs / token / budgets 用 monospace；
- 主任务视觉优先，观测台克制但持续可见；
- UI refinement 修改源 token / primitive，不追加无穷 override。

## Accessibility floor

- visible keyboard focus；
- usable touch targets；
- readable metadata；
- `prefers-reduced-motion`；
- mobile 不产生水平溢出；
- critical state 不只靠颜色；
- Runtime Observatory 的事实在窄屏仍有可达入口。
