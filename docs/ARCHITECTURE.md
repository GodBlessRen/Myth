# Myth v0.9 architecture

> Architecture Constitution: [ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md)  
> Composable map: [PLATFORM_MAP.md](PLATFORM_MAP.md)

## Runtime shape

Myth 不再把系统建模成固定的 “Decision → Routing → Dispatch → Execution” 层级，也不再使用 P0/P10/.../P1000 作为正式架构名称。

中心是稳定 Core：

```text
Goal → Run → Action → Attempt → Ticket → Receipt → Artifact → Verification
```

围绕 Core 的 Coordination / Control / Execution / Capability / State / Context / Memory / Personal State / Observability 等是**正交 Domain**。

Decision、Planning、Routing、Workflow、Parallel、Multi-Agent、Managed Agent、Personal Agent 是 **Coordination Strategy**；它们可以组合、替换或完全跳过。

外部模型、协议和基础设施通过 Port/Adapter 接入。OpenAI、Ollama、MCP、A2A、Browser、Shell、SQLite 都不能成为 Core 依赖。

代码中的 `MythComponents` 只负责装配和架构快照，不是执行 Kernel。`MythKernel` 仅作为 v0.6-v0.8 兼容别名保留。真正的执行事实仍由 `MythRuntime` / repositories / execution adapters 管理。

## Personal-Agent foundation

v0.9 新增显式长期对象：

- `Goal`：长期意图，可以跨多个未来 Run；
- `Trigger`：user/timer/schedule/event/webhook/email/file-change/agent-event；
- `Personal State`：显式 preference/permission/account-like state。

Personal State 与 Memory 分离。Memory 是经历产生的上下文数据；Memory 文本不能授予权限。Trigger 当前只持久化和暴露 API，不会自动后台执行；因此该 Domain 标记为 `connected` 而不是 `usable`。

## Naming

产品和新代码统一使用 `Stop`。旧 `abort` API / DB 字段只为升级兼容保留。Stop 的语义是“不再调度新工作”，不是宣称已发出的外部调用被撤销。

成熟度统一为 `exists / connected / usable / hardened / planned`。

## Dependency direction

This is a single-machine modular monolith. Both the conversation and exact-verification use cases follow a hexagonal boundary:

```text
CLI / Web (inbound adapters)
          ↓
Workspace / AgentRuntime (composition facades)
          ↓
ConversationAgent / AgentDriver (application use cases)
          ↓
ConversationRepository + ConversationExecution / Agent ports
          ↑ implementation
SQLite repositories / local execution adapters
          ↓
DecisionRuntime / MythRuntime / providers / objects / workspaces
```

`acceptance.py` contains pure verification; `conversation.py` contains pure conversation projection, lexical ranking and arithmetic. `application/` depends only on domain data and ports, with no SQL, filesystem or provider implementation. Architecture tests guard these dependencies. Existing P1/P2 runtime services remain concrete behind execution adapters; the entire repository has not completed this migration.

Ports expose transaction-sized operations rather than cursors. The repository owns state; the driver owns sequencing; execution adapters own I/O and reconciliation. Neither model output nor browser state grants authority.

## Conversation workspace

`SqliteWorkspaceRepository` owns projects, sessions, messages, document metadata/chunks, settings, turn/step state and tool operations. `Workspace` wires this repository to `LocalConversationExecution` and `ConversationAgent`. Web workers own independent runtime connections. The repository returns data rather than SQL cursors; the use case does not import providers or databases.

Turn admission fixes model/settings, project scope/instructions, retrieval results and recent 30 messages. One transaction creates the shared Run/accounts, conversation Turn/user message and session title/event. Request identity covers session, message, model settings and attachments. Duplicate retries return the original turn; conflicting identities and a second active turn are rejected. A project change affects new turns, not an already-fixed scope.

`workspace_steps` persists STARTED → DECIDED → DONE. A conversation-specific request key binds the model invocation to its step using the existing model ledger. The local OS run lock serializes drivers. Invalid proposals consume a step; a saved proposal/receipt is reused after restart. Ask-user decisions and current question IDs commit together; only the matching answer resumes that turn.

Tool output/read snapshots are published as content-addressed objects. In one transaction, a tool operation fixes result/target/digest, validates current turn authority and decision ownership, reserves tool/write budgets and issues a Ticket. Only then can a generated file be written. The execution adapter publishes a receipt and the repository settles it once. A crash after an output write can be reconciled against the fixed digest; a missing or different file remains UNKNOWN and is never blindly rewritten. Read/search/calculation results fixed in the Ticket can be recovered without rereading changed sources. Uncertain liabilities move to unknown-held; late evidence settles them once. Pre-Ticket object publication can leave orphans; GC is deferred.

Conversation stop blocks new tool admission and final answers. Already-ticketed effects can still complete and settle their actual facts. It is not an undo operation. A normal reply commits its message and COMPLETED state atomically, with execution_verified=false. Shared Run SUCCEEDED here means a completed conversation turn, not an independently verified goal. Generated artifact cards require resolved tool operations; answer/session exports merely download existing text. Neither produces the exact-verification use case's goal delivery record.

## Exact-mode submission and acceptance

1. Validate 1–16 explicitly allowed, distinct-basename UTF-8 files, at most 1 MB each.
2. Read baseline bytes once, calculate sequential exact-rule results, publish baseline objects and managed copies.
3. In one SQLite transaction, persist Run, Agent, all accounts, acceptance manifest, settings and initial event/note.

The manifest fixes every allowed file's baseline and expected digest. It includes unchanged files. Rules come from the inbound submission; model decisions cannot alter the manifest. Entry identity covers goal, provider/model, baseline, rules and limits. Reusing a request ID with different content is a conflict. Object publication precedes the DB commit and may leave unreferenced objects/workspaces on rejection or repeated submissions; garbage collection is deferred.

The exact-patch primitive operates on UTF-8 bytes without newline normalization. The trusted contract is exact replacement, not unrestricted interpretation of a prose goal. Missing rules are `INCONCLUSIVE`.

## Durable Agent steps

`agent_steps` records `STARTED → DECIDED → DONE`. Opening a new step and advancing the cursor are atomic. A model request key (`run_id:step:number`) is bound to its invocation in the Model Ticket transaction. A committed response can be recovered and parsed without calling the provider again. Invalid JSON is still charged and consumes a step; a new step gets a new request identity.

The local per-run OS lock prevents two drivers from executing the same run concurrently and releases on process exit. It is not a distributed lease. HTTP workers each own a runtime connection and expose `driver_active` only as a live projection. After restart, a user can explicitly continue; the service does not auto-dispatch uncertain work.

`ask_user` finishes the step and stores the question in the same transaction. An answer must match the current decision ID and is consumed once. Provider/model and run settings remain fixed during continuation.

## Tool execution and atomicity

`file.patch_exact` uses the existing durable chain:

```text
decision → Action + Attempt + reservations + decision binding (TX-Intent)
         → StartTicket + control revision validation (TX-Start)
         → managed file effect
         → durable Receipt → budget settlement
         → tool note + step consumption (one transaction)
```

The unique decision-to-Action binding is inserted with the Action intent. Restarting after a file receipt but before consuming the step reuses that Action and receipt. Recovery processes the actual Action owned by each attempt rather than the most recent Action. Agent-owned runs cannot receive P1 delivery through lower-level recovery.

`file.read` is a projection of managed bytes into a content-addressed immutable object. Its internal read ticket, snapshot reference and `tool_calls/read_bytes` debit commit together. Reconsuming the same decision returns the recorded snapshot without a second debit. The page limit is 3,000 Unicode characters; accounting uses UTF-8 bytes. It does not claim a two-transaction external-effect protocol for a read.

SQLite is atomic only for its own state. File effects and provider requests are outside DB transactions. After a Ticket, absent durable outcome means `UNKNOWN`; reserved liability remains held, and continuation never resends that uncertain operation. Late model receipts settle the appropriate reserved/unknown-held account once. Actual usage absent from a receipt remains held.

## Stop semantics

Stop semantics commits Agent/Run control state and increments the control revision. Intents without a Ticket become `NOT_STARTED` and release reservations in that transaction. Already-ticketed operations can still complete; late outcomes remain recorded. The driver rechecks stop after model I/O; tool admission and delivery also check durable authority. Stop semantics does not undo effects or erase accounting.

## Independent goal verification and delivery

The model's `request_completion` is only a claim. The pure verifier requires:

- fixed trusted rules and no declared remaining work;
- unique, own-run, durable success evidence;
- each cited receipt digest matches the current managed candidate;
- every allowed file matches its fixed expected complete digest;
- evidence covers every changed file.

The report, completed step, Agent state, delivery and events commit together. Downloads require an Agent `SUCCEEDED` delivery and serve the expected content-addressed object after digest verification. This binds delivery to immutable accepted bytes even if someone later changes a managed display file. No Agent goal delivery is inferred from a successful P1 patch.

## Context and knowledge

The event/receipt ledger is the durable execution record. Context compilation creates a deterministic bounded projection: recent notes, shortened old previews, the latest tool result, user corrections/rejections, fixed acceptance and tool evidence references. Dropping optional history never rewrites that record. Required context over 32,768 UTF-8 bytes or a serialized model request over 65,536 bytes stops before a model Ticket. These are byte guards, not accurate token estimates.

Conversation projection uses native role messages and a 42,000-byte guard including system instructions, project context, knowledge and current activities. Optional old messages/previews are removed before required context; the persistent record is unchanged. The shared 65,536-byte serialized-request guard also applies. Ollama uses a compact action discriminator and per-tool native argument-object schema, projected back to the same StepDecision, to avoid nested JSON-string failures in small models; remote adapters retain the original string transport. Provider output still passes StepDecision validation and local capability admission.

Knowledge is local UTF-8 text, chunked at 1,800 characters with 200 overlap. English tokens and Chinese bigrams rank shared/current-project chunks; retrieval examines at most 10,000 chunks per query and returns up to eight. Source IDs, chunk indices and immutable digests accompany results. Import metadata/chunks commit together after object publication. Archived documents are excluded from new retrieval while historical previews remain readable. No embedding model, vector database, semantic summarizer or autonomous long-term memory is implemented. Retrieval is source data, never execution authority.

## Persistence

Existing P1/P2/P3 tables remain. New additive tables:

| Table | Ownership |
| --- | --- |
| `agent_contracts` | frozen acceptance manifest |
| `agent_settings` | provider configuration |
| `agent_steps` | durable decision consumption cursor |
| `model_request_keys` | one model invocation per step identity |
| `agent_tool_bindings` | one Action per tool decision |
| `agent_reads` | immutable internal read snapshot and debit |

Old P3 runs lacking a contract remain inspectable; verification never fabricates acceptance for them. Automatic migration/resume of legacy in-flight runs has not been validated.

v0.5 adds workspace_projects, workspace_sessions, workspace_turns, workspace_messages, workspace_steps, workspace_documents, workspace_chunks, workspace_settings and workspace_operations. These use additive CREATE TABLE IF NOT EXISTS statements; no old table is dropped. Real upgrade acceptance for legacy active runs remains planned.

## Web boundary

The packaged vanilla HTML/CSS/JS calls a loopback-only JSON API. Host and port must match the local listener; mutations require JSON and same-origin when Origin is present. There is no CORS endpoint. CSP, frame denial and `textContent` rendering limit accidental browser execution of file/model text. This is a local, single-user service, not an authenticated multi-user platform or hostile-code sandbox.
