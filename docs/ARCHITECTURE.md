# Myth v0.4 architecture

## Dependency direction

This is a single-machine modular monolith. The Agent slice now follows a hexagonal boundary:

```text
CLI / Web (inbound adapters)
          ↓
AgentRuntime (composition facade)
          ↓
AgentDriver (application use case)
          ↓
AgentRepository / AgentExecution (ports)
          ↑ implementation
SqliteAgentRepository / LocalAgentExecution (outbound adapters)
          ↓
DecisionRuntime / MythRuntime / providers / objects / workspaces
```

`acceptance.py` contains pure domain verification and context projection. `application/` depends only on the domain, decision data and ports; it imports no SQL, filesystem or provider implementation. The architectural test protects this direction. P1/P2 remain existing concrete runtime services behind the execution adapter; the entire repository has not yet completed this migration.

Ports expose transaction-sized operations rather than cursors. The repository owns state; the driver owns sequencing; execution adapters own I/O and reconciliation. Neither model output nor browser state grants authority.

## Submission and acceptance

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

## Cancellation

Cancellation commits Agent/Run control state and increments the control revision. Intents without a Ticket become `NOT_STARTED` and release reservations in that transaction. Already-ticketed operations can still complete; late outcomes remain recorded. The driver rechecks cancellation after model I/O; tool admission and delivery also check durable authority. Cancellation does not undo effects or erase accounting.

## Independent goal verification and delivery

The model's `request_completion` is only a claim. The pure verifier requires:

- fixed trusted rules and no declared remaining work;
- unique, own-run, durable success evidence;
- each cited receipt digest matches the current managed candidate;
- every allowed file matches its fixed expected complete digest;
- evidence covers every changed file.

The report, completed step, Agent state, delivery and events commit together. Downloads require an Agent `SUCCEEDED` delivery and serve the expected content-addressed object after digest verification. This binds delivery to immutable accepted bytes even if someone later changes a managed display file. No Agent goal delivery is inferred from a successful P1 patch.

## Context and memory

The event/receipt ledger is the durable execution record. Context compilation creates a deterministic bounded projection: recent notes, shortened old previews, the latest tool result, user corrections/rejections, fixed acceptance and tool evidence references. Dropping optional history never rewrites that record. Required context over 32,768 UTF-8 bytes or a serialized model request over 65,536 bytes stops before a model Ticket. These are byte guards, not accurate token estimates.

This version has no semantic summarizer, long-term memory or RAG. Retrieval will be a separate port and a projection of trusted sources rather than a second source of execution truth.

## Persistence added in v0.4

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

## Web boundary

The packaged vanilla HTML/CSS/JS calls a loopback-only JSON API. Host and port must match the local listener; mutations require JSON and same-origin when Origin is present. There is no CORS endpoint. CSP, frame denial and `textContent` rendering limit accidental browser execution of file/model text. This is a local, single-user service, not an authenticated multi-user platform or hostile-code sandbox.
