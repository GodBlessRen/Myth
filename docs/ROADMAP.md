# Myth Roadmap — Breadth First, Depth Later

这里的路线不再使用 P0/P10/... 作为架构名称。

“先存在再优化”的意思是：即使未来有很多 Plan，也优先把长期边界、接口和最小行为铺出来，而不是把一个局部做到极深以后才考虑其他形态。

## 当前基线：v0.10

已经可用：

- Durable Run / Action / Attempt / Ticket / Receipt；
- Conversation + Agent Loop；
- Steer / Pause / Resume / Stop / Model / Thinking / Compact；
- Capability Registry；
- project.read/search、diff.preview、git.status/diff；
- ContextCompiler；
- typed Memory；
- Runtime Inspector；
- Goal / Trigger / Personal State 的持久化入口。

新增信息决策合同：

- Intent Pick：exists；尚未接管主请求；
- Information Resolution：exists；尚未 materialize L0/L1/L2；
- Information Delta：exists；尚未自动计算；
- Information Gain：exists；尚无校准 estimator。

已经存在但还需加深：

- Workflow；
- Routing；
- Multi-Agent；
- Managed Agent；
- Personal Agent；
- Skills；
- MCP；
- Evaluation；
- Evolution。

## Next — Execution

把真正高风险执行能力作为一个统一问题推进，而不是零散开放命令：

- admitted Test;
- bounded Shell profiles;
- Python executor;
- process tree + timeout;
- stdout/stderr Artifact;
- Ticket / Receipt / Usage / UNKNOWN / Recovery;
- human approval where required.

不开放模型生成任意 shell 字符串直接执行。

## Next — Coordination

让 CoordinationStrategy 真正进入主运行链：

- Direct;
- Agent Loop;
- Workflow;
- Router;
- Parallel;
- Multi-Agent child Run;
- Managed Agent via AgentPort.

目标是同一个 Core 承载不同组织策略，而不是为每种 Agent 复制 Runtime。

## Next — Personal Agent

在现有 Goal / Trigger / Personal State 基础上继续：

- Goal → many Runs;
- EventPort;
- Timer / Schedule / Webhook adapters;
- explicit preferences / permissions;
- approval gates;
- connected account references;
- background Run scheduler;
- proactive notification.

Trigger 只创建工作机会，不绕过 Control / Ticket。

## Next — Interop

- Skill loader;
- MCP tool/resource adapter;
- A2A AgentPort;
- managed-agent adapter;
- optional AG-UI-style interaction adapter.

协议只进入 Adapter；Core 不感知协议名。

## Next — Intent / Information

- Intent Pick 接入 Input/Trigger → Coordination；
- 先走规则 / 本地检索 / Jev / 小模型等低成本路径，必要时再升级 LLM；
- Knowledge/Memory 生成 L0/L1/L2 materialized views；
- Resolution Controller 决定是否升级信息分辨率；
- Information Delta 接入 Memory revision / conflict / supersede；
- Information Gain estimator 必须通过固定 eval 校准；
- 支持 expected gain per token / latency / tool cost；
- 不把相似度直接当 Information Gain。

## Next — Context / Memory / Retrieval

- memory conflict and supersede;
- Personal State 与 Memory 的冲突边界;
- RetrievalPort;
- optional vector / hybrid / rerank;
- token-aware Context budget;
- compaction summaries as derived artifacts.

Keyword baseline 继续保留用于可复现评测。

## Next — Verification / Evaluation / Evolution

- conversation acceptance profiles;
- fixed eval suites;
- replay as derived data;
- PASS / FAIL / INCONCLUSIVE / UNSUPPORTED;
- quality/safety gate before cost optimization;
- candidate policy registry;
- explicit promote / rollback.

Evolution 永远不能直接修改正在运行的 Run。

## Long horizon

只有出现真实部署需求后再深化：

- distributed workers;
- leases;
- remote execution;
- multi-user auth;
- organization policy;
- fleet scheduling.

边界可以先存在，复杂实现由真实需求触发。
