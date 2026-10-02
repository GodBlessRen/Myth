# Myth v0.6+ — Breadth-first Roadmap

当前策略：**先让整套平台骨架存在，再把每层从 wired 推进到 usable，再优化。**
不再用“某一块 95 分后才开始下一块”的方式推进。

完整层级见 [PLATFORM_MAP.md](PLATFORM_MAP.md)。

## Wave A — Skeleton complete

目标：所有长期层拥有稳定名字、接口、状态归属和最小合同测试。

- Durable Runtime
- Conversation
- Control Plane
- Capability Registry
- Context Compiler
- Memory
- Retrieval / RAG
- Workflow
- SubAgent
- Skills
- MCP
- Observability
- Evaluation
- Evolution
- Distributed Runtime boundary

验收：`MythKernel.snapshot()` 可以给出整个平台拓扑；planned 能力不会被广告为 executable。

## Wave B — Product control

**v0.8 已完成第一轮主链接入：**

1. persistent Control Command log + projection;
2. steer / pause / resume / abort;
3. turn 内 model / thinking switch;
4. compact one-shot context control;
5. unified Capability Registry 参与真实工具准入;
6. ContextCompiler 接管对话历史预算裁剪;
7. Runtime Inspector 读取 control / operation / event durable facts。

## Wave C — Capability surface

按原子适配器扩展：

- project.search ✅
- diff.preview ✅
- git.status / git.diff ✅
- test.run
- admitted shell.exec
- python.run
- web.fetch / browser adapter

所有真实 I/O 必须复用 Runtime admission/Ticket/Receipt/usage/recovery，不允许工具 SDK 隐藏重试。

## Wave D — Context / Memory / RAG

- Working / Episodic / Semantic / Procedural memory revisions ✅ 本地持久层 + episodic auto-write;
- memory provenance, conflict and revoke;
- RetrievalPort;
- lexical baseline retained;
- optional vector / hybrid / rerank adapters;
- token-aware ContextSnapshot and compaction.

## Wave E — Workflow / SubAgent / Skills / MCP

- persistent Workflow Run/Step;
- child Run for SubAgent;
- parent budget and capability delegation;
- Skill loader and capability requirements;
- MCP discovery mapped to local CapabilitySpec before admission.

## Wave F — Eval / Replay / Evolution

- fixed task suites;
- PASS/FAIL/INCONCLUSIVE/UNSUPPORTED;
- cost and token evidence separate from quality gates;
- replay as derived data;
- candidate policy registry;
- explicit promote/rollback; never self-modify live Runtime.

## Wave G — Product/UI

v0.7 已完成第一轮 Product Shell Reset：

- Chat remains center;
- Projects / Knowledge / Session Management 已降为 Context surface;
- right Runtime Inspector 已接入当前真实的 Decision / Result / Budget / Context / Platform facts;
- visual tokens / layout / components 已整体重构，不再依赖旧 CSS override 层。

下一步继续补：

- Control strip: model / thinking / steer / pause / resume / abort ✅;
- Runtime Inspector: durable Tool Ticket / Operation / Control revision ✅，下一步补完整 Receipt / Verification / Recovery;
- streaming, diff and artifacts inline in conversation;
- Context / Memory drawers.

## P1000 boundary

Distributed workers, leases, remote execution and multi-user authentication stay planned until a real capacity/deployment requirement exists.  The boundary exists now so future growth does not force a redesign.
