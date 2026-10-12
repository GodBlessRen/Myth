# Myth React 19 Workbench · preview implementation

The legacy application remains the production entrypoint. This isolated React app is the **replacement candidate**, not a second runtime. Risk, release gates and rollback are defined in [../docs/FRONTEND_REWRITE_PLAN.md](../docs/FRONTEND_REWRITE_PLAN.md).

## Run locally

Start existing Python service:

```bash
python -m pip install -e .
myth --root . web
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://127.0.0.1:5173/next/**. Development Vite proxies `/api`, `/logo*.svg` and `/fonts` to local `http://127.0.0.1:8765` (or `MYTH_BACKEND`). It intentionally rewrites the Origin only for that loopback developer proxy; the shipped bundle makes same-origin API calls and does not include that proxy.

## Checks

```bash
npm run typecheck
npm test
npm run build
# Browser Matrix prerequisites: Playwright Chromium + running Python fixture and Vite proxy
npm run test:browser
```

React and Python must never mutate the same DOM. `/` continues to serve the old workbench. The build currently produces an isolated `dist/` artifact for validation; it is not packaged or served by Python until the explicit cutover gates are met. No schema changes or credentials are required to experiment.

## Technology and ownership

React 19 + TypeScript strict + Vite + HeroUI v3/Tailwind CSS v4 for standard controls; TanStack Query holds disposable read snapshots, Zustand holds UI-only preferences. `api.ts` is the sole HTTP seam; no hidden POST retry. Browser use of `sessionStorage` stores **only hashes and UUIDs of pending submission identities**, never credential fields. Run, memory, permission, budget and verification are exclusively owned by the Python backend.

The preview currently implements the main conversation, raw tool facts and artifacts, Runtime Observatory, sessions, projects, knowledge, goals/plans, settings and OAuth entrypoints. Advanced parity gates (all tool-result semantics, focus traps, no-loss import, model pool and multi-provider real testing) remain mandatory before production routing changes.

## Current known limitations

- Current Python service exposes HTTP snapshot polling, not a cursor-based SSE protocol. Never describe this UI as token streaming.
- CI now verifies 5 viewport widths × light/dark themes × (home, completed transcript, UNKNOWN) with the real local Python/SQLite fixture, retains exact-revision screenshots, and checks no passive POST writes. This is **30 visual states, not 130 full legacy states**, and does not prove full feature parity.
- This is a source preview; wheel packaging of Vite output, a committed npm lockfile and the production /next/ static allowlist require a later reproducibility / release PR.
- A network timeout after creating a new session has uncertain outcome; read back sessions before creating another. Run message submissions reuse an idempotency identity.
- Do not claim current visual acceptance based on type checks; compare real screenshots at all gate widths and both themes.
