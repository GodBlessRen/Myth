# Myth Roadmap

## 当前主线

> 能否长期、可靠地替一个人推进真实工作？

```text
Long-term Goal
  -> Current State / Next Action
  -> explicit due opportunity or user request
  -> admitted Turn / Control
  -> Observe / Act / Verify
  -> durable checkpoint
  -> later Session / restart
  -> continue the same Goal
```

已有运行基线：持久 Goal/Turn、Execution Cursor/Driver Lease、UNKNOWN 核对、跨会话延续、一次性/固定间隔计划、三栏 Runtime Observatory、固定任务运行器。版本变化只记录在 CHANGELOG。

## Next 1 — 解决固定任务中的真实失败

继续用 `evals/daily-v1.json` 的完整集合，每题至少三次，同时保留 simple-loop 路由消融组。记录成功、未验收完成、人工接管代理指标、模型/工具/Token、重复工作、恢复、耗时和 Context 取舍。

优先分析模型给错工具参数、忽略已有 Goal 进度、无必要询问、完成自述与产物证据不一致。区分 Model / Context / Tool / Provider / Runtime / Product workflow；保留原始失败，不改题刷分。

## Next 2 — 受限验证执行

代码类任务需要运行验证。先设计一个显式 admitted test profile，固定 argv、工作副本、timeout、process tree、stdout/stderr Artifact、Ticket/Receipt/Usage 与 UNKNOWN/recovery。

`test.run` 仍为 planned。文件语法解析或一次 smoke PASS 不等于任意代码安全执行；模型不能提供任意 shell 字符串。

## Next 3 — 按失败补 Tool / Context / Memory

候选包括更好的原文分页、Artifact verification、Memory conflict/supersede、项目观察与检索对照。只有固定任务或连续自用证明需要时才增加能力；先解决已经发生的问题，不先造更多 Layer。

## Next 3.5 — Harness efficiency 实测

现有骨架已接入 Observation exact recall、grounded Compact seed、deterministic successor fusion、Evidence Receipt verifier、optimization economics/reachability 与 capability-floor eval 合同。下一步不是继续堆机制，而是用真实长轨迹回答：

- provider-visible projection 实际减少多少 input token；
- exact recall 增加了多少额外 Tool round-trip；
- Compact 的 upfront/cache debt 在多少请求后回本；
- fused successor 是否真实减少 model calls，而不降低 Verification；
- 哪些任务出现 outcome flip，具体机制是否真的触发；
- 同一候选在 held-out final suite 是否仍保持 capability floor。

只有这些证据成立，才把实验参数从 policy candidate 提升为默认策略。

## Next 4 — 连续自用与计划故障注入

连续自用 2–4 周，验证跨日 Goal 延续、模型断连、服务重启、长时间暂停、重复计划到期、核对后的继续。当前自动测试与小任务基线不能证明多周可靠性。

继续测真实 provider in-flight interruption 与 UNKNOWN reconcile，当前 daily suite 的恢复题只覆盖调用前安全中断。

## 冻结横向扩张

Workflow、Routing/Parallel、Multi-Agent、MCP/A2A 和更复杂 Evolution 暂不作为新增架构主线。保留现有合同，先积累可比较的工作证据。

## 永久不变量

- Goal / Memory / Model 不扩大权限。
- Trigger 只创造机会，执行仍经过 admission、Control 和 Ticket。
- UNKNOWN 先 reconcile，不盲 replay。
- 完成必须有 Artifact/test/receipt/external state 证据。
- 桌面第三栏常驻；窄屏仍有完整 Runtime 观测入口。
- 旧 Turn/Receipt/Artifact 不被未来策略倒写。
- Core 不感知模型厂商、MCP/A2A 等协议名。

## 长期方向

只有明确部署需求出现后再推进系统常驻服务、分布式 worker、远端执行、多用户授权、组织 policy 和 fleet scheduling。当前固定间隔计划不是通用 cron/Event Bus/Trigger DSL。


## v0.24 — Delivery workflow

实现说明见 [DELIVERY_WORKFLOW_V024.md](DELIVERY_WORKFLOW_V024.md)。本阶段增加终态收尾补偿、绑定交付摘要的验收、持久 Work item、受信项目 `test.run` profile、人工关注计量与 Runtime Delivery 观测。真实 2–4 周连续自用仍是发布闸门，不以测试夹具替代。


## v0.25 — SOTA Route

同任务重复执行不再只看成功率。已验收成功 Run 进入 SOTA Route 账本，比较工具调用、步骤、Token、写入、耗时、改动行数和人工关注；新 Run 可读取冻结的历史较省路径作为效率参考，明显绕路时只发 Drift / Replan 信号，不强杀。

术语保持简单：`Champion / Loser / Working / Drift`。完整边界见 [SOTA_ROUTE.md](SOTA_ROUTE.md)。

下一阶段固定任务每题继续重复多次，同时报告 trajectory variance，并联合分析 Reasoning Cost / Reasoning Summary / Action Path，验证 SOTA Route 是否让同模型更稳定地复现 Champion 路线，而不是只提高平均成功率。

Historical Replay World 只作为这批重复真实 Run 的实验性离线利用方式：它复用已发生路径降低策略研究成本，但不能替代新的真实试次、固定 Eval 或发布验证。
