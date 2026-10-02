# Myth Roadmap — Breadth First, Depth Later

这里的路线不再使用 P0/P10/... 作为架构名称。

“先存在再优化”仍成立，但 v0.11 开始明确第二阶段原则：**已经存在的合同优先进入真实请求链、故障链和评测链；不继续用更多抽象掩盖未闭环的能力。**

## 当前基线：v0.14

已经可用：

- Durable Run / Action / Attempt / Ticket / Receipt / Artifact / Verification；
- Conversation + Agent Loop；
- Steer / Pause / Resume / Stop / Model / Thinking / Compact；
- Control revision 跨 SQLite 连接原子分配；
- Capability Registry；
- project.read/search、diff.preview、git.status/diff；
- ContextCompiler + 42 KB conversation projection；
- typed Memory + provenance / revision / revoke；
- Episodic Memory 默认 Project / Session scope，显式 global Memory 继续可用；
- Goal / Trigger / Personal State 持久化入口；
- Goal 在 Run/Turn admission 前校验，goal_id 进入 request identity；
- knowledge.search + paginated knowledge.read L2 evidence；
- Runtime Inspector；
- Intent Pick 的保守 deterministic 快路：严格纯算术 0 次模型调用，其他输入回退 Agent Loop。

信息决策当前真实状态：

- Intent Pick：**connected**；strict arithmetic + conservative local_retrieval 已进入 Turn admission，未使用通用 LLM 分类器；
- Information Resolution：**connected**；Rule Controller 在 admission 固定 L0/L1/L2，同一来源保持固定 digest；
- Evaluation：**usable**；foundation-v1/v2/v3 + executable Runner + durable Eval Ledger + paired policy comparison 已接通；
- Information Delta：exists；尚未自动计算 conflict / supersede / revision delta；
- Information Gain：**connected（offline）**；paired fixed-case estimator 已接通，未进入 live admission；无 paired evidence 就保持 uncalibrated。

已经存在但还需加深：

- Workflow；
- Routing / Parallel；
- Multi-Agent；
- Managed Agent；
- Personal Agent；
- Skills / MCP；
- Evaluation；
- Evolution。

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

## Next — Gain calibration depth before live policy use



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
- Resolution Controller 下一步从静态规则升级为 eval-calibrated policy，但必须保留 fallback；
- Information Delta 接入 Memory revision / conflict / supersede；
- 扩大 paired eval 到 ordinary QA / local retrieval / multi-step read / artifact / recovery；
- 为 token / latency / tool / context 成本建立**显式、版本化** cost model，而不是硬编码权重；
- 只有跨足够 fixed cases 稳定后，才允许 Gain 影响 Resolution Controller；
- 不把 similarity、confidence 或 relevance score 直接命名为 Information Gain。

## Next — Interop

- Skill loader；
- MCP tool/resource adapter；
- A2A AgentPort；
- managed-agent adapter；
- optional AG-UI-style interaction adapter。

协议只进入 Adapter；Core 不感知协议名。

## Next — Verification / Evolution

- conversation acceptance profiles；
- replay as derived data；
- quality/safety gate before cost optimization；
- candidate policy registry；
- explicit promote / rollback。

Evolution 永远不能直接修改正在运行的 Run。

## Long horizon

只有真实部署需求出现后再深化：

- distributed workers；
- leases；
- remote execution；
- multi-user auth；
- organization policy；
- fleet scheduling。

边界可以先存在，复杂实现由真实需求触发。
