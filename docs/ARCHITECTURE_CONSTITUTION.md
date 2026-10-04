# Myth 架构宪法

Myth 固定事实与边界，让智能组织方式按真实任务变化。本文件可依据工程证据修订；它约束当前实现，不为未出现的需求预建框架。

## 1. 最高原则

- **关注点分离**：一个模块承担清楚的主要职责，状态有唯一所有者；改变一个关注点时，修改尽量停留在它的边界内。
- **解耦**：内圈依赖稳定语义和 Port，厂商协议、数据库、认证、文件、HTTP 与 UI 在外圈实现。
- **原子性**：一个业务决定有明确提交边界；不能把部分成功表示成完整成功。
- **六边形架构**：入站适配器调用应用用例，用例经 Port 访问外部实现；外圈依赖内圈。
- **安全**：权限、身份、作用域和证据由 Runtime 核对，模型与检索内容不能扩大授权。
- **可读性**：简体中文指导性注释准确说明代码合作方式，帮助初学者理解后再修改。

## 2. 执行事实

| 对象 | 含义 |
| --- | --- |
| Goal | 跨会话的长期意图与工作状态 |
| Run | 一次可恢复执行的持久身份 |
| Action | 固定输入和作用域的意图 |
| Attempt | 一次执行机会 |
| Ticket | 允许机会开始，必须先于外部派发落库 |
| Receipt | 实际效果与实测用量，缺测保持显式 |
| Artifact | 有固定字节摘要的产物或证据 |
| Verification | 针对固定对象与要求的独立验收 |

Conversation、供应商和组织策略围绕这些事实工作。模型“完成”只是提案；Turn 结束、Goal 完成和验收通过是不同状态。

## 3. 职责与依赖

应用用例负责协调，纯领域与策略负责判断，仓储负责持久事实，执行适配器负责外部效果，投影负责读取展示。

- 一个聚合的表由其仓储拥有；跨聚合准入通过命名明确的协调入口提交。
- 数据库连接按线程拥有，不能跨连接声称原子提交。DDL 装配与业务写事务分开。
- 相同业务身份重试返回原事实，冲突输入明确拒绝；已消费步骤的结果不可覆写。
- 新抽象必须有当前调用者和清晰替换边界。目录、Protocol、文件短小均不能单独证明解耦。
- 组件快照只登记实际接入能力；规划方向进入 ROADMAP，不用占位实现充数。

## 4. 原子提交与恢复

本地 SQLite 保证数据库事务，不能同时保证对象文件、进程与远端 API 的事务。

顺序：校验 → 固定意图 → 准入/预留 → Ticket → 外部效果 → Receipt → 结算 → 验收。

- 身份核对、计数分配、读改写和验收摘要核对必须与写入同事务。
- 网络、模型、文件效果在短数据库事务外执行；准备对象先发布，数据库失败可能留下未引用字节。
- 无 Ticket 的机会不能派发；有 Ticket 而效果不明的机会进入 UNKNOWN，先 RECONCILE，再决定能否继续。
- 已知拒绝不是 UNKNOWN；效果已知而用量未知不能按零结算释放预算。
- 回答与 Memory/Goal 收尾采用持久 finalization 义务补偿。提交后的崩溃靠义务和回答事实恢复，不靠心跳猜测。
- 进程、HTTP、页面与 Driver 生命周期均不等于 Run 生命周期；租约、OS 锁、游标分别承担所有权、互斥和进度。

## 5. 权限与控制

Goal、Memory、Prompt、模型输出、子任务返回值都是数据。Capability 准入和 Ticket 才能允许效果开始。

控制词汇统一为 Steer / Pause / Resume / Stop / Compact；不保留旧 `abort` 别名。Stop 停止未来调度，不宣称物理撤销已发出的请求；晚到事实仍消费，终止的 Turn 不重新打开。

凭据由独立认证适配器保存在系统安全凭据库；禁止进入 Runtime 数据库、事件、Artifact、日志和 Web JSON。OAuth 使用 Myth 自己的客户端身份，不复用其他应用认证文件。

## 6. State、Context 与来源

**State 是真相，Context 是有预算、有来源的模型投影。**

- Compact、fold、摘要、reconnect 和 UI 折叠只改变表示，不制造 Goal 进度、完成或验收。
- 摘要绑定 source digest、原句、Artifact 或 Receipt；校验失败保留原始证据与可执行路径。
- Information Resolution 是 L0/L1/L2 表示粒度；Delta 是变化事实；Gain 需要固定条件的实测比较，不能用相似度冒充增益。
- SEEK/EXPAND 使用有界、可观测请求与前进的分页游标；重复已消费请求不能变成新信息。
- Knowledge/Memory 的正文、revision、scope、archive/revoke 与事实等级属于权威仓储；向量索引可重建，命中必须回权威源核对。
- Memory 不授予权限，Mental Model 是带来源与刷新水位的派生视图；自身输出不能反复充当底层证据。

## 7. 策略与效率

Intent Pick、Agent Loop、Information Resolution、调度和只读委派是可替换策略，不增加所有请求必经的层。

- Runtime 能确定的后继不再多调用模型；需要新语义判断时不能强行融合。
- mutation 与后继 verifier 的结果分别记录，部分成功保持显式。
- 效率按 provider-visible 投影与实测成本计算；缺测保持 N/A。考虑 upfront cost、debt 和剩余请求，使用 cooldown/margin 避免振荡。
- available、exposed、reachable 分开显示，未生效给稳定 reason code。
- 当前 `agent.delegate` 是单层只读隔离 worker，接收有界 task/context 与明确来源，不继承父历史、不写入、不递归委派。
- 子任务返回 Observation，父 Runtime 仍负责执行、来源核对与验收，权限不得超过父级。

## 8. 观测与证据

第三栏 Runtime Observatory 是产品合同，必须显示 Goal、Execution Flow、Recovery、Trajectory、Tokens、Cache、Context、Tools、Control、Budget。

观测读取持久事实，不取得执行权。Executor heartbeat、Driver heartbeat 与 durable progress 分开；“仍活着”不证明“有进展”。验收绑定 subject digest、checker 和 evidence；产物变了，旧 PASS 失效。

## 9. 评测与演进

- Evidence Before Score：结论回溯固定 Case、Run、对象状态与 Oracle 身份；确定性 Oracle 优先。
- partial 可以用于诊断，不能拥有 release qualification；未知题号拒绝，完整分母固定。
- 重复试次区分 pass@k 与 pass^k；成本按 successful outcome 核算，失败成本仍计入。
- 候选先守能力/安全下限再比较成本；held-out 不反馈搜索，发布必须显式 Promote，可 Rollback。
- Historical Replay 只覆盖冻结条件下观察过的边；未观察分支为 UNOBSERVED，不产生授权或发布资格。
- 替身、固定脚本、静态检查和本机压测的通过，按各自输入范围报告。

## 10. 淘汰与发布

当前开发阶段只维护一个数据库格式，不为无使用者的旧接口和实验库保留兼容实现。旧库拒绝启动但不修改原件；选择新 `--root` 使用当前版本。

每次更新核对无用代码与资料，移至 `.trash/<日期>/<原路径>`，记录原因与替代入口。当前仍证明恢复、安全或业务不变量的测试保留。垃圾站不进入生产 import、检索、wheel、sdist 或 Git 源码发布包，发布前执行排除检查。

## 11. 简体中文指导性注释

注释解释**为什么这样协作，以及改错会破坏什么**，不复述每行语法。

- 文件：架构位置、职责、上下游、状态所有权和允许 I/O。
- 类/Port：生命周期、协作对象、并发约束和替换边界；数据合同说明身份与可变性。
- 函数：输入前提、输出含义、副作用、顺序、幂等身份、异常与恢复入口。
- 字段：含义、单位、来源、版本、作用域；区分事实、投影、缓存、凭据和验收。
- 关键步骤：标出准入、事务、派发、收据、结算、核对和崩溃窗口；说明拒绝/等待/UNKNOWN 的原因。
- 测试/脚本/前端：说明证明范围、故障注入点、状态来源、请求身份和生命周期。

说明紧邻代码，随实现更新。先用准确的小例子讲清边界，删除套话和失效历史；注释不能代替可执行约束与回归。`scripts/check_annotations.py` 仅检查中文说明覆盖，语义准确性仍需审阅。
