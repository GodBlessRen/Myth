# Myth Architecture — P1 + P2

## Runtime contract

```text
User goal
  ↓
Run
  ├─ Model Action → Model Attempt → Model Ticket → Provider
  │                                      ↓
  │                           durable model receipt
  │                                      ↓
  │                               StepDecision
  │                               (proposal only)
  │
  └─ Tool Action → Tool Attempt → StartTicket → managed effect
                                         ↓
                                   Receipt / reconcile
                                         ↓
                                    Verification
                                         ↓
                                      Delivery
```

The two paths deliberately share the same ideas: stable intent, one execution opportunity, durable launch authority, durable facts, separate accounting, and recovery without blind replay.

## P2 provider boundary

`src/myth/providers/base.py` defines a tiny provider port:

```text
check()  -> readiness only
invoke() -> ModelResult
```

Built-ins:

- `OllamaProvider`: local `/api/chat`, structured schema, provider token counts.
- `OpenAIApiKeyProvider`: OpenAI Responses API with `OPENAI_API_KEY`.
- `PiOpenAIProvider`: OpenAI Responses API, but authentication is delegated to upstream Pi OAuth.

Pi remains the owner of browser login, refresh token, credential locking and `auth.json`. Myth consumes only a short-lived resolved bearer token. This follows the same separation used by SoL-Pi: the extension/runtime does not take ownership of Pi authentication.

## StepDecision contract

Exactly one of:

- `tool_call` — proposal containing a capability ID and arguments;
- `ask_user` — required information is missing;
- `request_completion` — a claim that still requires independent verification.

The provider-facing JSON schema uses a fixed object shape so Ollama and OpenAI can share one transport contract. `arguments_json` contains the tool argument object as JSON text; the Runtime parses and validates it again.

## Model durability

A model call is not a hidden helper call:

```text
Prepare frozen ModelRequest
  → TX Model Intent + all meter reservations
  → Model Ticket
  → provider I/O
  → publish raw response object + local model receipt
  → TX settle provider usage
  → validate + commit StepDecision
```

If the provider call raises after a Ticket and no durable response receipt exists, the model Attempt becomes `UNKNOWN`. P2 does not silently call the provider again because that could double-charge or produce a different decision.

If a durable response receipt exists after a crash, `recover-model` can settle it and reconstruct the StepDecision without another provider call.

## Completion boundary

P2 intentionally stops after StepDecision. A model `tool_call` does not yet auto-create/execute a Tool Action. This prevents a subtle but serious mistake: treating “one proposed tool finished” as “the user's overall goal is verified”.

The next layer is:

```text
StepDecision(tool_call)
  → Runtime permission/scope validation
  → Tool Action/Attempt/Ticket
  → tool Receipt
  → next Model Decision or Verification
```

## Physical design

P1 tables remain unchanged. P2 adds only three compact physical structures:

- `model_invocations`
- `model_reservations`
- `step_decisions`

Logical Model Action / Attempt / Ticket / Receipt identities are still explicit even though P2 does not create a separate table for every noun.

## Explicit simplifications

- one driver / one SQLite writer;
- one model request per `plan` command;
- no automatic model-output repair yet;
- no multi-turn Agent loop yet;
- no automatic tool execution from StepDecision yet;
- no hidden SDK retry inside Myth provider adapters;
- OAuth login UI/refresh/storage remains in Pi;
- no distributed lease/exactly-once claim.
