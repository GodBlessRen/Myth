# Myth React 19 · 独立预览 / React Preview

React 19 is the **replacement candidate**, not an additional agent runtime. Python/SQLite own all durable truth. This PR deliberately retains legacy `/` as a functional rollback and serves the vendored React shell at `/next/`. See [migration and rollback contract](../docs/FRONTEND_REWRITE_PLAN.md).

## Run installed local preview (no npm required)

```bash
python -m pip install -e .
myth --root . web
```

Open `http://127.0.0.1:8765/next/`. Open `http://127.0.0.1:8765/` for the legacy UI. Both use the **same** Python REST contract and local SQLite, with no database/schema migration. The React preview uses the exact wheel-packaged, allowlisted and SHA-256 recorded static resources. Missing scripts/variants get a 404; no arbitrary asset file-serving.

## Develop locally (separate Vite, only during frontend development)

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/next/`. Vite's **development-only** loopback proxy forwards `/api`, logos and `/fonts` to `http://127.0.0.1:8765` (or `MYTH_BACKEND`). It rewrites only the loopback Origin so the existing Python request guard accepts requests; this proxy is not packaged. All production React API calls are same-origin.

To rebuild checked-in wheel resources:

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..
python scripts/stage_react_preview.py --dist frontend/dist --out src/myth/webui/react
```

Only the dedicated feature-branch `Vendor React 19 Preview` workflow may commit built assets and lockfile. Dependency installation/building happens in a separate **read-only** job; its artifact-only publish job has write permission but cannot execute npm scripts.

## CI gates

- **TypeScript strict + Vitest**: run `npm run typecheck && npm test && npm run build` inside `frontend`.
- **Exact bytes**: clean `npm ci` output must byte-match `src/myth/webui/react` including manifest. Unknown chunk paths are rejected.
- **Real browser/SQLite**: `npm run test:browser` exercises 5 widths × 2 themes × home/completed/UNKNOWN + keyboard focus, with real loopback Python fixture. CI runs the same matrix against both Vite and wheel-packaged `/next/`.
- **Real UI actions**: `npm run test:workflows` exercises drafts, new session, file upload, one admitted Turn and reload; guarded by real test backend, **never** live provider or real credentials.
- **Wheel**: Python `tests/test_react_preview_assets.py`, `scripts/validate_package.py`, HTTP content-type comparisons and wheel import validation remain mandatory.

## State / security

React Query owns disposable **read** snapshots, Zustand only stores UI preferences. `api.ts` is the HTTP boundary; no blind POST retry, no OAuth/API Key in React storage. A network error during a POST may have an UNKNOWN outcome. The runtime, budget, ticket, receipt, Goal, memory and permissions remain exclusively in Python.

### Current scope and hard release limitations

Functional preview already includes chat, tools, artifacts, observatory, sessions, projects, documents, goals and schedules, provider setup/OAuth and multi-model draft settings. **It is NOT the production default**. Further work is still required before any `/` cutover: **all 130 legacy Browser Matrix states with parity**, true subagent/Diff inspection, provider capability/pricing parity, permissions and real external provider smoke tests, streaming/reconnect, performance, accessibility, keyboard and responsive polish. Vite tests are **not** production acceptance. Keep fallback `/` throughout this release.

HTTP session snapshots currently use polling, **not** cursor-based token streaming. Don't market this preview as streaming.
