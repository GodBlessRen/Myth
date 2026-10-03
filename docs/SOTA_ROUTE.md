# Myth v0.25 — SOTA Route

## 目标

同一个任务、同一个模型、同一套冻结环境下，LLM 仍可能走出完全不同的执行路径。

Myth v0.25 不再只问：

> 任务成功了吗？

还会继续问：

> 在成功的前提下，这次是不是走得更省？

这个机制统一叫 **SOTA Route**。产品界面只保留四个简单词：

- **Best**：当前没有已知成功路径在所有可比较成本上都更省。
- **Beaten**：已经存在一条成功路径，在所有可比较成本上都不更贵，并且至少一项更省。
- **Learning**：当前 Run 还没有进入已验收成功集合，或还没有历史样本。
- **Drift**：当前执行已经明显比历史成功路径更绕，提醒下一步重新评估。

内部不会使用一个神秘总分，也不会要求用户理解 Pareto Frontier。

## 第一原则：先成功，再省

SOTA Route 的准入条件是：

```text
Run COMPLETED
    +
Acceptance PASSED
    +
当前 subject_digest 仍有效
    +
同任务 / 同模型条件 / 同冻结环境
    ↓
才允许比较成本
```

模型自己的“我已经完成”不产生 Best 资格。

验收离开 `PASSED` 后，原记录保留审计，但立即退出 SOTA Route 比较集合。

## 比较什么

基础成本全部来自 Runtime 已有持久事实：

- model calls
- tool calls
- steps
- input + output tokens
- write bytes

双方都真实测量时再比较：

- provider/tool work time
- changed lines
- human attention

缺测不是 0，不参与该维度比较。

### 为什么不用一个总分

例如：

```text
Run A: tools 3, tokens 12k, time 90s
Run B: tools 5, tokens  8k, time 50s
```

在没有用户显式成本权重时，Myth 不假装知道谁“总分更高”。

只有当一条路径在所有可比较基础成本上都不更差，并至少一项更好时，才会把另一条标记为 `Loser`。

## 环境怎么判定

每个新 Turn 准入时冻结 `sota_route_environment`。

无本地项目时，比较键包含：

- 用户任务
- provider / model / thinking / temperature / context / step budget
- 历史消息边界
- Knowledge 来源与版本
- Memory revision
- Goal revision
- Intent / Information Resolution / Policy bindings

有关联本地项目时，额外对允许的文本源码做 SHA-256 状态摘要。

跳过：

- .git / node_modules / venv / cache
- .env / key / pem
- 明确敏感配置目录
- 二进制与超大文件

项目状态无法完整冻结时，状态显示 `NOT_COMPARABLE`，不会错误宣布 Best。

## 路径保存什么

SOTA Route 保存的是**可观察执行路径**，例如：

```text
project.search
→ project.read
→ project.patch_exact
→ test.run
→ git.diff
→ reply
```

不会保存或推断模型隐藏 Chain-of-Thought。

大段源码、Prompt、patch 正文也不会复制到 SOTA Route 账本；只保留 capability、step、稳定 decision id 和少量定位字段。

## 如何真正影响下一次执行

历史 Best 不只是统计图。

新的同条件 Turn 在准入时会冻结一份短提示：

```text
SOTA Route
known route: project.search → project.read → patch → test → reply
known low cost: 4 tools / 5 steps / 8k tokens

Use as an efficiency prior only.
Do not skip required evidence or verification.
```

模型仍然可以因为新证据偏离历史路线。

SOTA Route 不扩大工具权限、不修改预算、不跳过验收。

## Drift：发现“开始绕了”

执行过程中 Myth 会把当前成本和历史 Best 对比。

首版触发条件保持保守：

- tools 比历史较省值多 2 次以上；
- steps 比历史较省值多 2 步以上；
- tokens 超过历史较省值 50%。

出现 Drift 后，不会强杀 Run。

下一次模型决策会收到明确提醒：

> 当前路径已经明显更绕。重新评估剩余工作，避免重复读取、重复检索和无必要改写；如果新证据确实需要更长路径，继续执行并保留验证。

因此：

```text
Drift ≠ Failure
Drift ≠ Auto Stop
Drift = Replan signal
```

## 和 Evolution 的关系

```text
成功 Run
  ↓
SOTA Route
  ↓
找到更省的重复模式
  ↓
固定评测
  ↓
Candidate Policy
  ↓
Evolution
  ↓
Promote / Rollback
```

**SOTA Route 负责发现。Evolution 负责证明和发布。**

一个偶然的漂亮 Run 不会自动改变生产策略。

## Runtime Observatory

第三栏新增 `SOTA Route` 区：

- State
- Compared runs
- Tool calls: current · best
- Steps: current · best
- Tokens: current · best
- Work time: current · best
- Changed lines: current · best
- Drift
- Action Path
- Compare scope

原有 Delivery / Execution / Recovery / Trajectory / Tokens / Context / Tools / Budget 全部保留。

## API

- `GET /api/workspace/turns/{run_id}/sota-route`
- `GET /api/workspace/sota-routes?limit=50`

这些接口只读取路径账本，不触发模型/工具执行。

## 关键不变量

1. **PASSED 才能进 SOTA Route。**
2. **省不等于对。先验收，再比较。**
3. **环境不够确定时，不宣布 Best。**
4. **SOTA Route 不保存隐藏 CoT。**
5. **历史路线只是 prior，不是强制计划。**
6. **Drift 只请求重新评估，不擅自停止。**
7. **SOTA Route 不直接 Promote 策略。**
8. **所有比较来自 durable facts，不从 UI 文本猜测。**

## 下一步实测

把现有固定任务从“每题至少三次”升级为：

```text
same case × same model × same frozen environment × N trials
        ↓
success / acceptance
        ↓
trajectory variance
        ↓
SOTA Route
        ↓
drift / repeated waste patterns
```

重点测：

- tool call 方差
- token 方差
- wall time 方差
- changed-line 方差
- human attention 方差
- 同一模型被 SOTA Route 提示后，方差是否下降

核心研究问题：

> Harness 能不能让同样聪明的模型，更经常走向自己已经证明过的高效成功路径？


## Reasoning Analysis

SOTA Route 把模型可观察的“思考侧”固定拆为三个事实：

- **Reasoning Cost**：供应商实际报告的 reasoning tokens、模型 wall time 等；缺测保持 N/A。
- **Reasoning Summary**：供应商公开返回的推理摘要。它可以帮助发现为什么某次 Champion 路径更直接，但不是隐藏 Chain-of-Thought。
- **Action Path**：Myth 实际观察到的 tool / ask / reply 序列。

若供应商返回公开 Reasoning Summary，Champion 的摘要最多取有界片段进入未来同条件 Run，作为规划先验；当前证据、权限、验收与测试仍必须重新核对。

隐藏 CoT 不可见时，Myth 明确保存 `unavailable`，不反推、不伪造。
