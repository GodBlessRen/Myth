# Myth

**Myth is a minimal durable Agent Runtime, not another tool-calling loop.**

The core rule is simple:

```text
Agent / LLM = proposes
Runtime     = authorizes + persists + executes + accounts
Verifier    = decides whether completion is proven
```

## Current milestones

### P1 — durable local effect

The first milestone proves one boring task carefully: import a UTF-8 text file into a managed workspace, replace an exact string a fixed number of times, survive process death around the side effect, verify the immutable expected result, and publish a Delivery.

### P2 — durable model decision

P2 adds provider-neutral `StepDecision` calls without letting the model bypass Runtime:

```text
Goal
 ↓
Model Intent + Budget Reservation
 ↓
Model Ticket
 ↓
Ollama / OpenAI / Pi-managed ChatGPT OAuth
 ↓
Durable Model Receipt
 ↓
Usage Settlement
 ↓
StepDecision (proposal only)
```

A model `tool_call` does **not** execute the tool and does **not** mark the Run successful. The next runtime layer will validate the proposal, create the normal tool Action/Attempt, execute it, then return to decision/verification.

## Providers

### Ollama — local

Start Ollama and make sure your model is installed, then:

```bash
myth provider-check --provider ollama --model <model>
myth --root . plan --provider ollama --model <model> \
  --allow-file example.txt \
  "replace foo with bar in example.txt"
```

The adapter uses Ollama's local `/api/chat` endpoint and requests structured JSON output. No credential is required.

### OpenAI API key

Set `OPENAI_API_KEY` outside the repository:

```bash
myth provider-check --provider openai --model <model>
myth --root . plan --provider openai --model <model> "decide the next step"
```

### ChatGPT subscription through Pi OAuth

Myth intentionally does **not** implement or store OpenAI refresh tokens. It delegates login/refresh/storage to the upstream Pi runtime.

Install Pi:

```bash
npm install --global @earendil-works/pi-coding-agent
```

Open Pi and run:

```text
/login openai
```

Choose **Sign in with ChatGPT**. After Pi has stored the OAuth credential:

```bash
myth provider-check --provider pi-openai --model <model>
myth --root . plan --provider pi-openai --model <model> "decide the next step"
```

At request time Myth calls Pi's public:

```text
pi auth print-bearer-token --provider openai --min-expiry 10m
```

Pi refreshes the OAuth credential under its own credential lock. Myth uses the returned bearer token only for the current request; it is not persisted in Myth SQLite, artifacts, receipts, logs, or Git.

Upstream Pi: https://github.com/earendil-works/pi

## P1 quick start

Requires Python 3.12+.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Run a managed exact patch:

```bash
myth --root . patch example.txt --old foo --new bar --count 2
```

Recovery after an interrupted file run:

```bash
myth --root . recover <run_id>
```

Inspect a P2 model Run:

```bash
myth --root . model-status <run_id>
myth --root . recover-model <run_id>
```

## Properties already protected

- stable request identity rejects same ID with different content;
- `Action` and `Attempt` are separate identities;
- TX-Intent commits an Attempt and all resource reservations atomically;
- a durable Ticket is required before file or model I/O;
- uncertain post-Ticket outcomes remain `UNKNOWN` rather than being blindly repeated;
- effect truth and usage truth are independent;
- model request/response artifacts and token usage are durable;
- model output is a proposal, never a Receipt or completion authority;
- file tool success cannot directly complete a Run without Verification;
- original user files are not silently overwritten in P1.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Privacy defaults

Local runtime state, SQLite databases, `.env*`, keys and `.runtime/` are gitignored. P2 can send the model prompt/context to a selected remote provider. Use Ollama for content that must remain local.

## Current boundary

Myth remains a **single-machine modular monolith**. It does not claim distributed exactly-once execution, hostile-code sandboxing, arbitrary user-directory transactions, or a complete autonomous Agent loop.
