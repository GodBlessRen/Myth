# Myth P1 Architecture

## Runtime contract

Myth P1 deliberately proves a small set of strong properties before adding an LLM, RAG, memory, multi-agent scheduling, or RSI.

```text
User request
   ↓
fixed baseline + acceptance
   ↓
Action (business intent)
   ↓
Attempt (one execution opportunity)
   ↓
TX-Intent + atomic budget reservation
   ↓
StartTicket (durable launch authority)
   ↓
managed file effect
   ↓
Receipt journal / reconciliation
   ↓
TX-Settle
   ↓
VerificationReport
   ↓
Delivery
```

## Five boundaries that must remain true

1. **Proposal is not authority.** A future model may propose an Action; only Runtime can reserve, ticket, execute, and settle it.
2. **Ticket is not success.** A Ticket means execution became possible. After a crash, absence of a response does not mean absence of an effect.
3. **Effect and usage are independent.** Recovery may know that the file reached the expected digest while still holding usage as unknown.
4. **Verification is completion authority.** A successful tool outcome cannot directly set `Run=SUCCEEDED`; Delivery requires a matching PASS report.
5. **UNKNOWN stays unknown.** If neither the receipt journal nor managed content proves the result, recovery blocks instead of blindly replaying a write.

## Physical design

P1 persists only what is needed to prove durable execution:

- `runs`
- `actions`
- `attempts`
- `tickets`
- `receipts`
- `accounts` + `reservations`
- `events`
- `verification_reports`
- `deliveries`

Concepts such as ContextSnapshot, AuthorizationDecision, ApplyJob, CorpusRevision, MemoryRevision, Replay, Evaluation, and Evolution remain future layers until a real use case needs their own identity, lifecycle, or recovery semantics.

## Crash windows covered by P1

### Effect happened, durable receipt exists, DB settlement did not happen

Recovery reads the receipt journal, validates the frozen envelope identity, and performs TX-Settle. The file operation is not repeated.

### Effect happened, process died before receipt publication

For the v1 local exact-patch tool only, recovery compares the fixed managed file against the fixed expected digest. If it matches, the effect is resolved as successful while usage remains `UNKNOWN_HELD`.

### Ticket exists, no receipt, content does not prove the expected effect

The Attempt becomes `UNKNOWN`; related reserved usage is held. P1 does not guess that the operation never ran and does not blindly replay it.

## Explicit simplifications

- One driver / one SQLite writer.
- One writer per managed workspace.
- One exact UTF-8 patch capability.
- No arbitrary shell.
- No editing of the original user directory; Delivery points to the managed verified artifact.
- No model adapter yet. Scripted planning isolates Runtime correctness from model randomness.
- No distributed lease/exactly-once claim.

The next layer should add one real model adapter that can only produce a structured decision and must reuse the exact same Runtime path.
