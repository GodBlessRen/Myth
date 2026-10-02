# Myth Roadmap — Breadth First, Depth Later

这里的路线不再使用 P0/P10/... 作为架构名称。

“先存在再优化”仍成立，但 v0.11 开始明确第二阶段原则：**已经存在的合同优先进入真实请求链、故障链和评测链；不继续用更多抽象掩盖未闭环的能力。**

## 当前基线：v0.18

已经可用：

- Durable Run / Action / Attempt / Ticket / Receipt / Artifact / Verification；
- Conversation + Agent Loop；
- Steer / Pause / Resume / Stop / Model / Thinking / Compact；
- Control revision 跨 SQLite 连接原子分配；
- Capability Registry；
- project.read/search、diff.preview、git.status/diff；
- ContextCompiler；Ollama projection budget 由 `num_ctx - output - reserve` 推导，OpenAI/Pi 保留 42 KB 本地 projection cap；
- typed Memory + provenance / revision / revoke；
- Episodic Memory 默认 Project / Session scope，显式 global Memory 继续可用；
- Goal / Trigger / Personal State 持久化入口；
- Goal 在 Run/Turn admission 前校验，goal_id 进入 request identity；
- knowledge.search + paginated knowledge.read L2 evidence；
- Runtime Inspector；
- Intent Pick 的保守 deterministic 快路：日期/版本/分数/百分比等形状冲突回退 Agent；calculator 拒绝会写 `RouteFallback` 后继续模型路径。

信息决策当前真实状态：

- Intent Pick：**connected**；strict arithmetic + conservative local_retrieval 已进入 Turn admission，未使用通用 LLM 分类器；
- Information Resolution：**connected + evolvable**；未来 Turn 从 durable Active Policy 读取 rule/fixed L0/L1/L2 config，并把 policy_id 固定进 snapshot；
- Evaluation：**usable**；foundation-v1/v2/v3/v4 + executable Runner + durable Eval Ledger + suite completeness 已接通；v4 新增 36 条 Intent 对抗 case；
- Evolution：**usable**；Cost Model / Calibration Matrix / Candidate Registry / explicit Promote / Rollback 已接通，不自动发布；
- Information Delta：exists；尚未自动计算 conflict / supersede / revision delta；
- Information Gain：**connected（offline evidence）**；paired fixed-case estimator + cross-case calibration matrix 已接通；不把 similarity/confidence 当 Gain。

已经存在但暂不横向扩张：

- Workflow；
- Routing / Parallel；
- Multi-Agent；
- Managed Agent；
- Skills / MCP；
- 更复杂的 Evaluation / Evolution。

这些能力只有在真实 Goal 工作流暴露明确瓶颈后才继续深化。

## 当前产品主线 — 先有再优

Myth 暂停横向堆 Multi-Agent / A2A / 更多 Evolution 抽象，先证明一个更重要的问题：

> 能否长期、可靠地替一个人推进真实工作？

当前黄金路径：

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

v0.18 已完成第一版：

- Goal durable work state：current / progress / next / waiting / last_run / revision；
- Goal 可绑定到任意新 Turn，并跨 Session 继续；
- Conversation 真实终态写 Goal checkpoint；
- Goal checkpoint 作为数据进入下一 Turn 的 bounded context；
- 第三栏 Runtime Observatory 固定保留并显示 Goal / Flow / Trajectory / Tokens / Context / Tools / Control / Budget；
- observability UI 身份加入 regression test，后续 UI 重构不能静默删除。

下一步优先级：

1. 10 个真实日常任务 × 重复运行，记录成功/接管/恢复/成本；
2. 最小 Timer/Schedule：只负责唤醒 due Goal，不绕过 admission/Ticket；
3. 根据真实任务失败补 Tool / Context / Memory；
4. 受限 `test.run`，让代码类任务可以验证候选改动；
5. 连续自用，再决定哪些高级架构值得继续。


## 已完成 — Correctness + Provider hardening

v0.16–v0.17 已完成：

- Intent arithmetic grammar 收紧，日期/版本/分数/百分比不再无前缀误路由；
- strong/weak knowledge cue 分级，弱词必须有足够 retrieval score；
- calculator rejection 记录 `RouteFallback` 并安全回退 Agent；
- foundation-v4：48 total cases，其中 36 条 Intent adversarial；
- ModelRequest 增加 `num_ctx` / temperature；
- Ollama 传递 `num_ctx` / temperature / keep_alive；
- Ollama 本地 Context budget 与 `num_ctx` 对齐；
- provider-confirmed truncation → durable FAILED，而非 UNKNOWN；
- ambiguous post-Ticket transport failure 继续 UNKNOWN、不盲目重发。

## 已完成 — Retrieval correctness foundation

v0.12 已完成：

- Knowledge search 去掉 rank 前 10,000 chunk 静默截断；
- Knowledge / Memory 使用可分页候选扫描并暴露 coverage diagnostics；
- project.search 增加 cursor / max_files / scanned_files / matched_lines；
- 同一 source_ref + digest 下接通 L0/L1/L2 projection；
- Keyword baseline 保持不变，便于后续公平比较 vector / hybrid / rerank。

因此现在可以区分 **candidate coverage failure** 与 **ranking failure**。

## 已完成 — Evaluation foundation

- Case / Observation / Verdict 合同；
- PASS / FAIL / INCONCLUSIVE / UNSUPPORTED；
- safety_regression 与 measured cost；
- 版本化 `evals/foundation-v1.json` 固定基线。

## 已完成 — Executable Evaluation + conservative routing

v0.13 已完成：

- 固定 EvalSuite → executable Runner → Observation → Report → Release Gate；
- `myth eval` CLI；
- foundation-v2 新增 local retrieval / L0-L1-L2 admission cases；
- retrieval evidence → Intent Pick → Resolution Plan → frozen Turn Snapshot；
- route/resolution/retrieval diagnostics 进入 Event 与 Context Report。

## 已完成 — Paired Evaluation + Information Gain foundation

v0.14 已完成：

- Eval Observation 持久化到本地 Ledger；
- 同 suite/version + 同 case/comparison key 的 baseline/candidate 成对比较；
- Workspace 策略依赖注入，Eval 可替换 Intent/Resolution policy 而不污染生产默认；
- foundation-v3 增加 resolution-sensitive marker case；
- Information Gain 的 quality delta 只来自 paired Verdict；
- cost 默认保持向量；只有显式 cost weights 才产生 weighted cost / gain-per-cost；
- INCONCLUSIVE / UNSUPPORTED pairing 明确保持 uncalibrated；
- `eval-history` / `eval-compare` / `gain` CLI。

## 已完成 — Evidence-driven Evolution Control Plane

v0.15 已完成：

- immutable versioned Cost Model Registry；
- cross-case Gain Calibration Matrix；
- durable Policy Candidate Registry；
- partial-suite eval 与 release evidence 明确分离；
- baseline/candidate 必须同 suite/version 且完整跑完 fixed suite；
- Release Gate + Calibration Gate 后 Candidate 才进入 ELIGIBLE；
- stale baseline Candidate 禁止覆盖新 Active Policy；
- Promote / Rollback 只更新未来 Workspace/Turn 的 Active Policy pointer；
- Turn snapshot 固定实际 information_resolution policy_id；
- policy release history / revision 可审计；
- CLI：cost-model-put/list、policy-create/evaluate/promote/rollback/status。

## Next — Harden evolution evidence, then expand policy surface





继续扩固定真实任务集，作为 Gain / Evolution 的共同地基：

- ordinary QA；
- local retrieval；
- multi-step project read；
- clarification；
- artifact generation；
- pause / resume / compact / restart；
- bounded deterministic fast path；
- exact verification cases。

记录：

- PASS / FAIL / INCONCLUSIVE / UNSUPPORTED；
- completion / error taxonomy；
- model/tool/token/latency cost；
- selected/dropped context；
- source expansion depth；
- artifacts / receipts / recovery facts。

没有固定 eval，不提升 Information Gain estimator，也不自动 promotion。

## Next — Coordination

在同一个 Core 上逐个接真实策略，而不是复制 Runtime：

- Direct；
- Agent Loop；
- deterministic Intent Pick；
- Local Retrieval route；
- Workflow；
- Router；
- Parallel；
- Multi-Agent child Run；
- Managed Agent via AgentPort。

每个 Strategy 必须有：fallback、budget、Control safe point、Ticket/Receipt 边界与 regression test。

## Next — Execution

高风险执行能力作为统一 executor 问题推进：

- admitted Test；
- bounded Shell profiles；
- Python executor；
- process tree + timeout；
- stdout/stderr Artifact；
- Ticket / Receipt / Usage / UNKNOWN / Recovery；
- human approval where required。

**不开放模型生成任意 shell 字符串直接执行。**

## Next — Personal Agent

在现有 Goal / Trigger / Personal State 基础上继续：

- Goal → many Runs；
- EventPort；
- Timer / Schedule / Webhook adapters；
- explicit preferences / permissions；
- approval gates；
- connected account references；
- background Run scheduler；
- proactive notification。

Trigger 只创建工作机会，不绕过 Control / Ticket。跨项目 Memory 默认不共享 episode；共享必须显式。

## Next — Intent / Information

- 在当前 deterministic/local_retrieval 之上，只增加可用 fixed eval 证明的 ask-user / local direct-answer 路径；
- 扩大可发布 policy surface：先 Intent Pick / Resolution，再考虑 Routing；每个 domain 单独 Active pointer 与 rollback；
- Information Delta 接入 Memory revision / conflict / supersede；
- 扩大 paired eval 到 ordinary QA / local retrieval / multi-step read / artifact / recovery；
- 扩充 Cost Model meter 观测（真实 token/latency/tool/context），保留版本化权重；
- 增加更大固定 suite、重复运行稳定性、置信区间与噪声检测，再允许更激进的 adaptive policy；
- 不把 similarity、confidence 或 relevance score 直接命名为 Information Gain。

## Next — Interop

- Skill loader；
- MCP tool/resource adapter；
- A2A AgentPort；
- managed-agent adapter；
- optional AG-UI-style interaction adapter。

协议只进入 Adapter；Core 不感知协议名。

## Next — Verification / Evolution hardening

- conversation acceptance profiles；
- replay as derived data；
- repeated-run variance / confidence evidence；
- candidate supersede / archive；
- promotion approval identity；
- release bundle export/import；
- multi-domain policy dependency checks。

Evolution 永远不能直接修改正在运行的 Run/Turn；发布只影响未来 admission。

## Long horizon

只有真实部署需求出现后再深化：

- distributed workers；
- leases；
- remote execution；
- multi-user auth；
- organization policy；
- fleet scheduling。

边界可以先存在，复杂实现由真实需求触发。
