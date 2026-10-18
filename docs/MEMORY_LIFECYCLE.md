# Memory Lifecycle

Myth 的 Memory 继续是一个正交 Domain，不新增第二套 Runtime，也不把向量库升级成事实数据库。

## Stable shape

```text
source facts / Run / user assertion
        ↓
Memory revision
  + provenance
  + Evidence
        ↓
immutable revision snapshot
        ↓
freshness check
        ↓
L0 / L1 compact projection
        ↓ explicit EXPAND
L2 evidence projection
```

## Evidence

Evidence 只回答“这条 Memory 基于什么”，不等同 Verification，也不能授予执行权限。

两类 Evidence：

- `evidence_ref`：外部稳定来源，例如 run / commit / document。若没有可比较版本水位，freshness 保持 `untracked`。
- `source_memory_id`：引用另一条 Memory。写入时固定对方当前 revision；后续来源 revision 改变或被 revoke，依赖 Memory 的 freshness 变为 `stale`。

Myth 不把相似度、proof_count 或 freshness 直接升级成 `verified`。

## Current Facts 与历史

Historical Truth 和 Current Facts 是两个维度。历史消息/Anchor 保留当时发生过的内容，不因后来状态变化而被重写；当前 Memory 中 `user_asserted / verified` 的可见记录则形成独立 metadata-only 版本摘要：

```text
visible user_asserted / verified Memory
        ↓ revision + scope + content digest
Current Facts digest
        ↓
Turn Continuity binding
```

这个摘要不包含 Memory 正文，也不使用 query score。它只回答“当前权威 Memory 状态有没有变化”，不制造客观真相。版本变化会使旧 continuity epoch fail closed 到 Context rebuild；普通 `context` Memory 和本轮 top-k recall 变化不会无谓击穿连续性。

## Immutable revision

`workspace_memories` 保存当前可见状态；`workspace_memory_revisions` 保存每个已经提交 revision 的不可变快照：

- text；
- fact_level；
- active；
- 当时的 Evidence JSON。

升级旧数据库时只为“当前已知 revision”补快照，不伪造无法恢复的历史 revision。

## Delta

模型或 Strategy 可以提出 Delta，但不能直接修改 Memory 表。

当前稳定操作：

```text
replace_text
add_evidence
remove_evidence
```

应用规则：

1. 调用方必须给 `expected_revision`；
2. Runtime 在 SQLite 写事务里重新核对当前 revision；
3. 所有操作先验证；
4. 任一操作失败则整批回滚；
5. 空操作列表是机械 no-op；
6. 成功后只产生一个新 revision 和一个新 immutable snapshot。

因此稳定原则是：

> LLM proposes delta; deterministic runtime validates and applies delta.

## Atomic Memory Action Batch（Last Mile）

允许明确的本机操作者调用 `POST /api/workspace/memories/actions`，请求体仅有 `{"actions":[...]}`。它复用唯一的 `SqliteMemoryStore.apply_actions()`，**不注册为 LLM 可自行调用的写权限工具**，也不接受模型提交 `verified` / `user_asserted` 事实等级。

- `ADD`：`kind/text/source_ref` 必需，scope/evidence 可选；只有全新 `(kind,source_ref)` 身份可创建，默认 `fact_level=context`；同源历史不会被静默覆盖。
- `UPDATE`：`memory_id/expected_revision/operations` 必需；仅支持现有 `replace_text/add_evidence/remove_evidence` 受约束 Delta，不改变事实等级/作用域/授权。
- `DELETE`：`memory_id/expected_revision` 必需；产生可审计的 `active=0` tombstone revision，绝不物理删除历史证据。
- 一次最多 16 个 Action；写入在同一 `BEGIN IMMEDIATE` 中完成。重复修改同一身份、版本不匹配、证据作用域越界或中途磁盘失败，**整批 rollback**。同一来源只能作为自身范围或更宽范围的证据，禁止私有 Memory 支撑全局陈述；显式禁止自证。
- **Crash / Retry**：CAS 与唯一来源键使已经提交的动作不能被不明结果盲目重复执行；这不是“重复调用返回同一成功响应”的请求日志。若提交回包丢失，客户端必须读取当前 revision/证据/变更水位 **reconcile**，再决定是否形成新提案。本次没有新增数据库表或更改 `SCHEMA_VERSION`，因此不破坏现有用户 Memory。
- **Projection**：SQLite 已提交后才同步 Milvus 等可重建向量索引，异常记录单独 `degraded`，不会把已成功的本地提交伪报为整体回滚。Recall 每次命中还要经权威状态 hydrate。
- **Episode**：同 `run_id`、同问答、同作用域的重复交付补偿返回既有 revision，不追加水位；同 Run 内容冲突返回 `IdentityConflict`，不篡改历史。

这是确定性事务和恢复合同；质量层面的真实性、回答证据充分性、远端 Milvus 召回率、模型 Token/时延与大规模并发吞吐仍需独立评测。不能用本地 unittest 或质量门禁通过宣称 SOTA。

最小回归：`python -m unittest discover -s tests -p test_memory_action_batch.py -v`；真实 HTTP 回归：`python -m unittest discover -s tests -p test_web_contract.py -v`。

## Transitive Truth Maintenance (Semantica-inspired)

A Memory-linked Evidence edge is pinned to the authority Memory's exact revision. Freshness is now checked across **the complete linked support closure**, not only direct parents. If any ancestor was revoked, replaced, missing, crosses an inadmissible scope, or forms a cycle, derived Memory is stale. Traversal limits (32 hops / 256 edges) fail closed rather than silently accepting unchecked ancestors. The deterministic report contains the failing ancestry path; external Evidence without a version remains untracked, **never auto-verified**.

Hindsight-style Knowledge Pages and Memory Recall reuse the same source owner. A materialized model inherits the supporting Memory's stale flag, and refresh preparation excludes stale inputs. Publication checks cited evidence again under the existing SQLite write transaction; a stale source cannot be laundered into a new backing Memory. No new schema, provider call, permission, or vector-index authority is introduced.

**Boundaries:** this checks structural support validity, not logical entailment, objective factual truth, or independently authenticated remote sources. More granular ontology mappings and learned evolution proposals remain outside this change. Existing Evolution release qualification and explicit Promote continue to own experiment governance.

Focused regression: `python -m unittest tests.test_memory_recall tests.test_knowledge_views -v`; full release gates remain in `AGENTS.md`.

## Read-snapshot qualification and refresh race fence

- **Evidence closure is snapshot-consistent:** `MemoryStore.freshness()` runs each stand-alone support traversal against one SQLite WAL read snapshot; a Recall or write transaction reuses its established connection snapshot. Evidence from two different database revisions must never combine to claim a valid chain.
- **Scope is a data-flow invariant:** session-scoped source Evidence cannot validate a global claim. Duplicate Episode settlement must preserve the derived Memory's matching scope instead of relaxing the security gate.
- **Materialized-view staleness is one state:** Knowledge Page `freshness` and `is_stale` agree even if backing Memory evidence fails without a new source watermark (for example integrity fault injection).
- **Freeze the source watermark before reading:** `prepare_refresh()` captures `observed_change_seq` before any retrieval/Memory content. If a writer changes even one source during preparation or LLM synthesis, `commit_refresh()` refuses the old synthesis under its existing SQLite write transaction. A watermark sampled *after* content would permit incorrectly binding a stale model answer to a new source revision.
- **Bounded source refill:** source selection considers up to 20 ranked candidates before filtering stale Evidence, then returns at most the requested count. This is a bounded quality improvement, not a claim of exhaustive recall or measured semantic accuracy.

Regression gates: `test_memory_action_batch.py`, `test_memory_lifecycle.py`, and `test_knowledge_views.py`; the full suite, CI and publication checks remain authoritative. This mechanism only checks source/version/scope validity, **not semantic entailment**.

## Evidence admission and Context delivery fence

Three input paths share one **authoritative Evidence admission**: `remember()`, direct `apply_delta()`, and bounded `apply_actions()`. Source Memory scope and active status are checked inside the same SQLite write transaction as the target revision. Rescoping an existing Memory without replacing its Evidence must also revalidate retained links. After writing the candidate state *inside the still-open transaction*, Myth checks its complete transitive support closure (revision pins, revoked ancestor, cycles, depth/edge limits); if invalid, the target write, revision, evidence snapshot, and change watermark all roll back.

The L0 memory tool and Context assembly use `search_view_report()`. Retrieval may consult the remote vector adapter **before** starting the authoritative read transaction. The selected candidates are then rehydrated under a single short SQLite snapshot, verifying active, exact revision, current scope, and complete support freshness. Stale or unauthorized candidates are excluded from model-delivered L0 text. A bounded 3× candidate oversample (max 20) refills valid results where possible; this is not exhaustive search and is reported as `candidate_rejected_after_search`. Explicit `resolve()` and timeline may surface stale historical revisions with an `is_stale` flag **only when provenance remains within the admitted scope**. A legacy missing or cross-scope source fails closed with `PermissionError` rather than revealing text through an explicit tool call.

Both the automatic L0 Context search and an explicit L0/L1/L2 `resolve()` read the current row, evidence and closure from one authoritative SQLite WAL snapshot; `resolve()` never combines an old body with a newer evidence report. The write-time check prevents ordinary bad data; the read-time check protects against changed dependencies and legacy/corrupted graph rows. **Neither check proves that the sentence is logically entailed by its evidence**; Ontology constraints and Eval-controlled evolution remain a separate quality problem.

Regression scope: `tests/test_memory_lifecycle.py` (write/scope/cycle/rollback), `tests/test_memory_recall.py` (model L0 Context leakage and source races), `tests/test_memory_action_batch.py` (atomic contract). Release checks still required per `AGENTS.md`.

## Progressive disclosure

首次 Recall 不展开完整 Evidence。

- L0/L1：`proof_count`、`freshness`、`is_stale`
- L2：完整正文、Evidence、freshness report

这样 Evidence-backed Memory 不会反过来破坏 Context budget。

## Indexed Lexical Retrieval（Highest Leverage）

原有检索逐页扫描全部可见 Memory 并对每条正文提取 English/CJK bigram。现在 Memory Store 在写事务内维护 `workspace_memory_terms` 词项倒排表：查询只扫描包含查询词的 postings，以旧有的集合交集计分、原始 rowid 逆序稳定 tie-break。**这是减少候选生成成本的索引，不是 BM25 模型质量提升声明**；更换排序器必须另行验证 Recall@K/权限/时延，不能凭名字认为更好。

- `remember / apply_delta / revoke / apply_actions` 都只经统一 `_record_change` 维护索引与 `change_seq`，任意中途失败同事务回滚。没有新写 API。
- 首次启动遇到旧 Memory 时比较索引与权威水位，只在落后时从当前 active 正文重建。
- 旧进程/直接 SQL 写入由 SQLite 触发器标记索引 dirty；该进程查询立即回退到完备词面扫描，重启后再原子重建。既不能漏召回，也不能让索引拥有权限。
- query 无可索引词项仍采用旧扫描；索引返回候选后继续接受 Scope/Revision/Active/Freshness 的权威快照检查，Milvus 仍只提供候选。
- Indexed 检索报告 `backend=memory-term-index`、查询词数、结果数；其 `scanned` 不是总可见 Memory 数。降级路径明确 `backend=memory-lexical-fallback` 与原因，不能伪装速度收益。

反例回归：`tests/test_memory_term_index.py` 验证英文、中文二元词、Scope、kind、稳定同分排序、批处理回滚、撤销、直接 SQL 写入与重启。全套跨平台 CI 仍为发布前提。

## Milvus boundary

Milvus 仍然只提供候选：

```text
Milvus candidate id/version
      ↓
SQLite hydration
      ↓
active / revision / scope / evidence / freshness
      ↓
Context projection
```

删除 Milvus 后，Memory revision、Evidence、freshness、Delta 和历史快照仍完整成立。


## Mental Model / Knowledge Page

Mental Model 是 **Materialized Memory View**，不是第五种 Memory Kind。

```text
source query + scope
        ↓
prepare_refresh()
        ↓ fixed Memory sources + observed_change_seq
        ↓
LLM / deterministic synthesis outside SQLite
        ↓
commit_refresh()
  - expected model revision
  - scope watermark check
  - evidence validation
        ↓
backing Semantic Memory
```

Mental Model 的正文唯一落在 backing Semantic Memory，因此原有 Evidence、revision、Milvus hydration、L0/L1/L2 和 revoke 语义全部复用，不复制一套内容生命周期。

Memory 每次 revision/revoke 都追加单调 `change_seq`。Mental Model 保存 `last_seen_change_seq`；自身作用域后来出现新变化就确定性变为 stale。刷新不会自动发生，避免后台隐式模型成本与不可观测副作用。

Knowledge Page 更薄：只保存 folder/page hierarchy 与 `mental_model_id`。树结构和内容状态分离，移动/重命名页面不会重写 Mental Model 正文。

## Automatic Mental Model Refresh

自动刷新是 **Durable Background Work**，不是 Memory 内部隐藏线程。

```text
Memory revision / revoke
        ↓
change_seq watermark
        ↓
Mental Model becomes stale
        ↓
opt-in Refresh Policy
        ↓
Refresh Occurrence + Lease
        ↓
Core Run + model budget
        ↓
DecisionRuntime: Intent → Ticket → Provider → Receipt
        ↓
Evidence + watermark re-check
        ↓
commit_refresh()
```

### Ownership

- Mental Model：拥有 source query / backing Memory / materialized content freshness。
- Refresh Policy：拥有是否自动刷新、最小间隔、冻结 Provider/Model 设置和 retry deadline。
- Refresh Occurrence：拥有一次 `model_id + source_change_seq` 的后台工作身份、状态与 lease。
- Core Run / DecisionRuntime：拥有模型预算、Ticket、Receipt、UNKNOWN 与 Provider Evidence。
- Durable Executor：只发现和驱动已准入工作，不成为新的事实数据库。

### Trigger is not permission

`stale` 只表示“派生视图可能需要刷新”，不授权直接调用模型。自动刷新必须显式 opt-in；Policy 建立时冻结 Provider / Model / thinking / context window / output budget，之后全局模型设置改变不会悄悄改变已有后台任务。

### Coalescing and leases

同一个 `model_id + source_change_seq` 最多只有一个 occurrence。`min_interval_seconds` 合并短时间内连续 Memory 写入。Durable Executor 有全局 worker lease；每个 Refresh Occurrence 另有 owner / heartbeat / lease。前者回答“谁是当前 worker”，后者回答“谁正在驱动这次 refresh”。

### UNKNOWN

Provider 在 Ticket 前明确未派发，可以退避后再次准入模型机会。Provider 已获 Ticket 后结果不明时，Refresh Occurrence 进入 `UNKNOWN`，Core Run 进入 `RECOVERING`；该 Mental Model 不再进入自动 due / dispatch 集合，必须先 reconcile 原模型 Attempt。

### Superseded synthesis

如果模型生成期间 source scope 出现新 change watermark，已经返回的 synthesis 保留 Provider Receipt，但不发布为 Mental Model；旧 occurrence 标记 `SUPERSEDED`，Core Run 标记 `CANCELLED`，下一次基于新 watermark 建新 occurrence。

### Previous content is baseline, not Evidence

上一版 Mental Model 可以作为文档演进基线以减少 prose drift：`previous content + new admitted evidence → revised document`。但 `previous_content` 永远不能自动进入 `evidence_refs`，最终 Evidence 只能映射到本次 admitted 的底层 Memory sources。


## Evidence-bounded multi-probe Recall

`memory.recall` is an opt-in SEEK tool that reuses the existing SQLite Memory authority, optional Milvus hydration, Runtime Tool Ticket/Receipt, and L0/L1/L2 disclosure. It does not introduce a separate memory database or a new background worker.

- `query` (required): one primary search string; `probes` (optional): at most three complementary searches. Duplicate probes are skipped before backend calls. Each search reuses the existing lexical/Milvus candidate path; fusion uses rank (RRF) rather than treating heterogeneous similarity scores as probabilities.
- `required_refs` (optional): up to four exact `memory:mem_<uuid>@<revision>` anchors previously observed via an admitted Memory view. Every anchor is rechecked in SQLite for visibility, active state, exact revision and linked-evidence freshness. Invalid anchors yield `missing`, `unavailable`, `revision_changed` or `stale_evidence`.
- `limit`: 1–8 L0 results, with valid required anchors admitted ahead of ranked optional candidates. Requests with more anchors than available slots fail before execution. All search probes and output bounds are fixed; this is not an autonomous unlimited retrieval loop.
- `evidence_gate.status`: `unverified` (no exact anchors), `anchored` (all exact anchors remain current) or `references_unavailable` (at least one anchor invalid). `answer_verified` remains **false** in all cases. An anchor is source-identity evidence, not an oracle of semantic sufficiency, causation, permission, or Verification.
- `retrieval.probes` and `degraded` preserve transparent search/degradation information. No unmeasured token savings or real-provider accuracy improvement is asserted. Duplicate sources are returned once and the original Memory revision history remains unchanged.

The new path is useful for revisiting previously cited memories across long-running work while reporting version mismatches explicitly. Semantic answer sufficiency remains the model/application's responsibility and should be evaluated against independent held-out tasks before introducing any automated rewrite of Memory facts.

Fixed local regression: `python -m unittest discover -s tests -p test_memory_recall.py -v` (or full discovery); see `tests/test_memory_recall.py`.
