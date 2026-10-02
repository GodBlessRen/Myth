# Myth

**Myth is a durable Agent Runtime: the model proposes, the Runtime authorizes, and verification decides completion.**

```text
Agent / LLM = proposes
Runtime     = authorizes + persists + executes + accounts
Verifier    = decides whether completion is proven
```

## P3 — the Agent actually runs

Myth now has a bounded single-agent loop:

```text
Goal
 ↓
Model Intent → Model Ticket → LLM
 ↓
StepDecision
 ├─ ask_user ───────────────→ pause / resume
 ├─ tool_call
 │    ↓
 │  Runtime scope + argument validation
 │    ↓
 │  Tool Action → Attempt → Ticket → file effect → Receipt
 │    ↓
 │  back to the model
 │
 └─ request_completion
      ↓
    AgentVerifier
      ↓
 Receipt + evidence_ref + current digest all agree?
      ↓
    Agent Delivery
```

A tool proposal cannot widen file scope. A tool success cannot finish the user goal. A model completion claim is accepted only when independent verification binds it to durable tool evidence.

### Current executable capability

P3 intentionally starts with one real tool:

- `file.patch_exact` — exact UTF-8 replacement inside a managed workspace.

The original user file is not overwritten. The verified artifact lives under the private `.runtime/workspaces/<run_id>/` tree.

## Start the local Web UI

Requires Python 3.12+.

```bash
python -m pip install -e .
myth --root . web
```

Myth opens:

```text
http://127.0.0.1:8765/
```

The Web UI is local-only by design. It has three surfaces:

- **Runs** — previous Agent runs;
- **Agent workspace** — goal, decisions, tool results, clarification and final answer;
- **Execution Ledger** — budget, Model Ticket, Tool Receipt, verification and durable events.

No CDN or frontend framework is required.

## Run the Agent from CLI

### Ollama

```bash
myth provider-check --provider ollama --model <model>

myth --root . agent \
  --provider ollama \
  --model <model> \
  --allow-file ./example.txt \
  "Replace foo with bar in example.txt"
```

### OpenAI API key

Set `OPENAI_API_KEY` outside the repository, then:

```bash
myth --root . agent \
  --provider openai \
  --model <model> \
  --allow-file ./example.txt \
  "Replace foo with bar in example.txt"
```

### ChatGPT subscription through Pi OAuth

Install Pi:

```bash
npm install --global @earendil-works/pi-coding-agent
pi
```

Inside Pi:

```text
/login openai
```

Choose **Sign in with ChatGPT**. Myth then resolves a short-lived bearer token through Pi at request time:

```text
pi auth print-bearer-token --provider openai --min-expiry 10m
```

Run:

```bash
myth --root . agent \
  --provider pi-openai \
  --model <model> \
  --allow-file ./example.txt \
  "Replace foo with bar in example.txt"
```

Myth never reads or writes Pi's `auth.json`; Pi remains the credential owner.

## Lower-level commands

P1 exact patch:

```bash
myth --root . patch example.txt --old foo --new bar --count 1
```

P2 proposal-only model decision:

```bash
myth --root . plan --provider ollama --model <model> \
  --allow-file example.txt \
  "decide the next step"
```

Inspect:

```bash
myth --root . agent-status <run_id>
myth --root . model-status <run_id>
myth --root . recover-model <run_id>
```

## Providers

- **Ollama** — local `/api/chat`, structured JSON decision output.
- **OpenAI** — Responses API using `OPENAI_API_KEY`.
- **Pi OpenAI** — Responses API using Pi-managed ChatGPT OAuth.

For content that must stay local, use Ollama.

## Design system

The P3 Web UI is original Myth code. Its visual system borrows principles, not source code, from:

- `video-shotcraft`: paper / ink / amber focus discipline and motion timing;
- `gc-minimal-zine-poster`: negative space and micro-editorial hierarchy;
- `frontend-slides`: grid-breaking editorial composition and restrained reveal motion;
- `lieflat-charts`: dense but legible runtime metrics;
- GSAP: timeline/easing principles. P3 uses native CSS/JS and does not vendor GSAP.

See [`docs/DESIGN.md`](docs/DESIGN.md).

## Properties protected

- stable request identity rejects same ID with different content;
- Model and Tool work both require durable Tickets;
- uncertain post-Ticket outcomes stay `UNKNOWN` rather than being blindly repeated;
- model usage and tool usage are budgeted independently;
- model output is proposal data, never a Receipt;
- model-proposed paths are constrained to the explicit `allowed_files` set;
- the only current tool is exact patch; there is no arbitrary shell;
- tool success cannot directly complete an Agent Run;
- completion requires durable evidence plus current artifact digest agreement;
- local Web binds only to loopback.

## Tests

```bash
python -m unittest discover -s tests -v
```

CI also compiles the package and runs hard process crash/recovery tests.

## Current boundary

Myth remains a **single-machine modular monolith**. It does not claim a hostile-code sandbox, distributed exactly-once execution, unrestricted computer use, or general-purpose autonomous coding yet. P3 proves one real Agent loop before adding broader capabilities.
