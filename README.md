# Myth

**Myth is a minimal durable Agent Runtime, not another tool-calling loop.**

The core rule is simple:

```text
Agent / LLM = proposes
Runtime     = authorizes + persists + executes + accounts
Verifier    = decides whether completion is proven
```

The first milestone intentionally implements one boring task extremely carefully: import a UTF-8 text file into a managed workspace, replace an exact string a fixed number of times, survive process death around the side effect, verify the immutable expected result, and publish a Delivery.

## Why this repository starts small

The architecture is designed around `Run → Action → Attempt → Ticket → Receipt → Verification → Delivery`. It does **not** materialize every future concept as a service or table. Memory, RAG, multi-agent orchestration, model routing, and RSI are postponed until the execution kernel has evidence that it is correct.

## What v0.1 already proves

- stable request identity: same `request_id` + different content is rejected;
- `Action` (business intent) and `Attempt` (execution chance) are different identities;
- TX-Intent atomically commits the Attempt and every resource reservation;
- a durable `StartTicket` is required before the file executor can run;
- process death after the file write is recoverable without blindly writing again;
- a durable receipt can be settled after restart without re-execution;
- effect truth and usage truth are independent (`UNKNOWN_HELD` is preserved);
- tool success cannot directly complete a Run; Delivery requires a matching PASS verification report;
- original user files are not silently overwritten in P1.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the exact boundaries and simplifications.

## Quick start

Requires Python 3.12+.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

Run a managed exact patch:

```bash
myth --root . patch example.txt --old foo --new bar --count 2
```

The verified result lives under the private local `.runtime/` directory, which is gitignored. The command returns the `run_id`, managed artifact path, budget projection, event stream, and Delivery metadata.

Recovery after an interrupted run:

```bash
myth --root . recover <run_id>
```

Inspect persisted state:

```bash
myth --root . status <run_id>
```

## Privacy defaults

This repository never requires secrets for P1. Local runtime state, SQLite databases, `.env` files, keys, and the `.runtime/` workspace are ignored by Git. Do not commit user documents or production traces unless they are intentionally sanitized test fixtures.

## Current boundary

v0.1 is intentionally a **single-machine modular monolith**. It does not claim distributed exactly-once execution, a hostile-code sandbox, arbitrary user-directory transactional updates, or a complete Agent product. Those guarantees require separate evidence and should not be inferred from the interfaces.
