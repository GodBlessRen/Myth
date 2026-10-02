# Myth Architecture — P1 + P2 + P3

## Runtime contract

```text
User goal
  ↓
AgentRuntime
  ↓
Model Action → Model Attempt → Model Ticket → Provider
                                      ↓
                           durable model receipt
                                      ↓
                               StepDecision
                      ┌────────┼───────────┐
                  ask_user   tool_call   request_completion
                      │          │                │
                    pause    Policy gate       Verifier
                                 │                │
                           Tool Action           PASS?
                                 ↓                │
                           Tool Attempt           ↓
                                 ↓             Delivery
                           StartTicket
                                 ↓
                           managed effect
                                 ↓
                              Receipt
                                 ↓
                           back to model
```

The architecture deliberately keeps three truths separate:

1. **proposal truth** — what the model suggested;
2. **execution truth** — what a Ticket/Receipt says happened;
3. **completion truth** — what independent verification can prove.

## P3 Agent loop

`src/myth/agent_runtime.py` is the orchestration layer. It does not replace the lower layers:

- Model calls still flow through `DecisionRuntime`;
- tool calls still use P1 `Action → Attempt → Ticket → Receipt`;
- budgets are still stored in the shared `accounts` ledger;
- uncertain provider/tool outcomes still stop rather than silently retry.

The loop is bounded by `max_steps`. Reaching the bound sets the Run to `BUDGET_EXHAUSTED`.

## Tool admission

P3 supports one admitted capability:

```text
file.patch_exact
```

Before creating the Tool Action, AgentRuntime validates:

- capability ID;
- argument types;
- positive expected match count;
- proposed path ∈ explicit `allowed_files`.

A rejected proposal is recorded and returned to the next model decision without creating a Tool Ticket.

## Completion verification

A model completion claim must cite one or more durable `evidence_ref` values.

AgentVerifier checks:

```text
cited evidence exists
AND cited Attempt == RESOLVED/SUCCEEDED
AND managed artifact still exists
AND sha256(current bytes) == action.after_digest
```

Only then does P3 write an Agent verification report and Agent Delivery and set the Run to `SUCCEEDED`.

## P2 provider boundary

`src/myth/providers/base.py` defines:

```text
check()  -> readiness
invoke() -> ModelResult
```

Built-ins:

- `OllamaProvider`
- `OpenAIApiKeyProvider`
- `PiOpenAIProvider`

Pi remains the owner of browser login, refresh token, credential locking and `auth.json`.

## Web architecture

`src/myth/web.py` is a thin loopback-only HTTP surface.

```text
Browser
  ↓
local JSON API
  ↓
AgentWebService
  ↓
AgentRuntime
  ↓
SQLite + content-addressed objects + managed workspaces
```

Agent execution runs in a daemon worker thread while the browser polls durable status. Each worker opens its own MythRuntime connection; the UI never owns runtime authority.

The frontend is static HTML/CSS/JS packaged inside the Python distribution. There are no CDN dependencies.

## Physical design

P1:

- `runs`
- `actions`
- `attempts`
- `tickets`
- `receipts`
- `accounts` + `reservations`
- `events`
- `verification_reports`
- `deliveries`

P2:

- `model_invocations`
- `model_reservations`
- `step_decisions`

P3:

- `agent_runs`
- `agent_notes`
- `agent_verification_reports`
- `agent_deliveries`

## Explicit simplifications

- single-machine modular monolith;
- one current Tool capability;
- original files are not overwritten;
- no arbitrary shell/computer-use surface;
- no automatic repair of malformed model JSON;
- no distributed lease/exactly-once claim;
- Web UI is local single-user and intentionally unauthenticated because it cannot bind beyond loopback;
- remote model content privacy depends on the selected provider.
