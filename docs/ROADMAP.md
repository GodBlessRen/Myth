# Myth Roadmap

## 当前基线：v0.18

Myth 已经有足够多的架构合同。当前阶段不再用更多抽象掩盖真实任务失败。

产品主线只有一句：

> **能否长期、可靠地替一个人推进真实工作？**

## 当前黄金路径

```text
Long-term Goal
  -> Current State
  -> Next Action
  -> admitted Turn
  -> Observe / Act / Verify
  -> durable checkpoint
  -> later Session
  -> continue the same Goal
```

v0.18 已经具备：

- durable Goal work state；
- 跨 Session / restart continuation；
- Conversation outcome -> Goal checkpoint；
- Goal checkpoint -> next Turn bounded context；
- Runtime Observatory 常驻第三栏；
- durable Runtime / Ticket / Receipt / UNKNOWN / Recovery；
- Intent correctness adversarial suite；
- provider context-window hardening；
- Eval Ledger / explicit policy release controls。

## Next 1 — 真实任务基线

建立 10 个真实日常任务，每个重复运行至少 3 次。

记录：

- task success；
- human takeover；
- wrong completion；
- recovery success；
- time to completion；
- model calls；
- input / output tokens；
- tool calls；
- repeated work；
- selected / folded / dropped context。

同时保留一个简单 Agent Loop 对照组。

目标不是刷分，而是明确失败来自：

- Model；
- Context；
- Tool；
- Runtime；
- Product workflow。

## Next 2 — 最小 Goal Wake-up

先只做最小 Timer / Schedule：

```text
due Goal
  -> wake up
  -> create admitted Turn
  -> run through normal Control / Ticket
```

不要先造 Scheduler Framework / Trigger DSL / Event Bus。

Trigger 只创造工作机会，不能绕过 admission、Control 或 Ticket。

## Next 3 — 按真实失败补能力

优先级由真实任务决定。

候选方向：

- Retrieval baseline（必要时再引入 FTS5 / hybrid）；
- 更好的 Context selection；
- Memory conflict / supersede；
- 文件/仓库观察；
- 受限 `test.run`；
- 更强的 Artifact verification。

没有真实失败，不升级成新 Layer。

## Next 4 — 受限验证执行

代码类工作真正需要的是验证，而不是任意 shell。

优先设计：

- admitted test profile；
- timeout；
- process tree；
- stdout / stderr Artifact；
- Ticket / Receipt / Usage；
- UNKNOWN / recovery；
- 明确 allowlist。

不开放模型直接生成任意 shell 字符串执行。

## Next 5 — 连续自用

连续自用 2–4 周，再决定是否深化：

- Workflow；
- Routing / Parallel；
- Multi-Agent；
- MCP / A2A；
- 更复杂 Evolution；
- adaptive Information Gain。

这些目前都**冻结横向扩张**。

## 永久不变量

- Goal / Memory / Model 不扩大权限；
- UNKNOWN 先 reconcile，不盲 replay；
- 完成声明必须有证据；
- 第三栏 Runtime Observatory 不删除；
- 历史 Turn / Receipt / Artifact 不被未来策略倒写；
- Core 不感知模型厂商 / MCP / A2A 等协议名。

## Long Horizon

只有真实部署需求出现后再推进：

- distributed workers；
- leases；
- remote execution；
- multi-user auth；
- organization policy；
- fleet scheduling。

长期方向存在即可，当前不为它们提前支付复杂度。
