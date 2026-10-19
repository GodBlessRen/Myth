# Myth React 19 replacement — risk register and rollback contract

Status: **implementation in progress; React preview is not a production cutover**. Decision: replace the full legacy web shell with React 19 + TypeScript + Vite; retain Python Runtime, SQLite and the existing HTTP contracts. This is an intentionally parallel replacement with **one atomic entrypoint cutover**, not a mixed DOM / React ownership scheme.

## Evidence and existing constraints

- `src/myth/webui/index.html`, `app.js`, `goals.js`, `inspector.js`, `studio.js` and `model-pool.js` currently own different UI regions of one static page. React must never mount into this page or mutate its elements.
- `src/myth/web_workspace.py:bootstrap/session/send/control/get/post` owns public projections and command dispatch. `src/myth/web.py` owns the local HTTP boundary and origin/host checks.
- `src/myth/web_assets.py:PUBLIC_ASSETS` is a closed asset whitelist; wheel packaging depends on explicit files. Never expose arbitrary build paths or add remote CDN.
- `tests/browser_matrix.cjs` covers five widths, both themes, 13 state views, accessibility and offline assets. Previous #71 Browser CI failed because of *exact palette expectations*, repaired separately by #72; UI acceptance still requires real screenshots and functional flows.
- The UI reads HTTP session snapshots on a reconnecting timer, including a transient answer preview from Responses/Ollama streams. Preview text is never a committed answer or tool decision. The browser transport remains polling rather than SSE.
- Unknown outcome is a real state. A network timeout does not imply a rejected POST, nor does Stop erase late effects.

## Risk register (priority / mitigation / gate)

| Risk | Priority | Mitigation | Required gate |
| --- | --- | --- | --- |
| React/legacy double-writes | Critical | Isolated React entrypoint and JS bundle; never mount both renderers on one DOM | Route isolation, inspect network and listeners |
| Lost message deduplication | Critical | Stable `request_id` tied to draft+session+attachments+settings; no blind POST retries | Timeout/reload/resend test verifies one Turn |
| UNKNOWN / paused / stopped conflated | Critical | Server snapshot is authoritative; explicit status controls, errors and reconciliation | Status matrix, crash/reconnect tests |
| Lost answer question identity | High | Reply to `WAITING_USER` with `question_id`, not a new Turn | Interaction parity test |
| Password/token exposure | Critical | OAuth/API keys remain in host's OS credential vault; never in localStorage or React logging | Security audit + CSP/offline gate |
| Lost session/focus on polling | High | Stable query keys by session ID, abort stale requests, preserve draft/scroll/focus | Keyboard, IME, rapid navigation and reconnect tests |
| Feature regression | High | Page-by-page parity ledger, block route cutover until core+settings+knowledge+goal+runtime all covered | All items green in parity matrix |
| UI accessibility/perf degradation | High | Native semantic controls, domain views, measured viewport/layout | 5 widths × 2 themes × 13 states and keyboard tests |
| Broken release / wheel | Critical | Build Vite offline static assets before allowlisting; pinned dependency lockfile; verify package bytes | install-wheel + HTTP asset checks |
| API schema drift | High | Typed narrow adapter and run/session fixtures; no destructive backend schema migration | API contract tests against real Python fixture |

## Migration shape: parallel implementation, atomic cutover

1. **P0 — contracts + safe preview:** Build `frontend/` as an isolated React 19 app and reuse the existing `/api/workspace` backend. Dev server proxies API to the local Python service. Existing `/` remains unchanged.
2. **P1 — full functional parity:** Finish chat, multi-turn messages, tools, Inspector, sessions, projects, knowledge, goals, schedule, settings, OAuth and model pool. Cross-route navigation must not create business work. `Request-ID` preserves business idempotency; requests with UNKNOWN outcomes require explicit reconciliation.
3. **P2 — packaged preview:** Lock dependencies, run Vite build in a release job, copy outputs into explicit allowlisted `src/myth/webui/react/*` paths and serve `/next/`. Verify wheel, no CDNs, CSP and browser tests. **Do not register paths before packaged outputs exist.**
4. **P3 — atomic cutover:** Only after parity gates pass: switch `/` to the built React entrypoint and keep the legacy shell at `/legacy/` via explicit whitelist. Both use one Python service; old frontend assets remain for at least one release cycle. No production database changes.
5. **P4 — retirement:** After actual-user stability, run automated release + rollback drills. Remove legacy files only through separate audited PR; delete unused scripts and obsolete tests only when equivalent coverage exists.

## Rollback playbook

Preconditions: old static files and the exact previous wheel/release are preserved; Python/SQLite schema remains unchanged.

- **During preview:** No rollback needed. Navigate to the legacy `/` or disable the preview route. The preview must never become a backend state owner.
- **After cutover:** Change the two explicit static route mappings so `/` again points to legacy `index.html` and `/next/` continues to serve React, then redeploy. Alternatively restore the previous wheel if compatible (no database migrations). Do not delete or reset data.
- **On uncertain POST outcome:** First GET the session by identity and reconcile server facts; use the original request_id if intentionally retrying, never generate a new identity for the same request.
- **Stop criteria:** any wrong-side-effect, credential disclosure, unacknowledged submit duplication, unresolved UNKNOWN represented as completion, inaccessible recovery controls, or missing core workflows.

## State and adapter ownership

| Owner | Data | Rule |
| --- | --- | --- |
| Python Runtime / SQLite | Runs, Attempts, tickets, receipts, budgets, goals, messages, control revisions, permission, verification | Sole durable truth |
| HTTP adapter | Request/response shape, timeout, errors, provenance, abort | No hidden POST retries |
| TanStack Query | Read-only snapshot cache keyed by identity | Cache is disposable; never commit execution |
| React component state / Zustand | Visible page, drawer, current draft, density, local selection, focus | Non-authoritative; must not infer success |
| OS credential store | OAuth and provider secrets | Browser never receives or stores secret material |

## Release parity ledger

- [ ] Chat: new session, draft preservation, send, retry/UNKNOWN reconciliation, waiting answer, attachments, stop, pause/resume, steering, model/thinking switch, compact, reconnect
- [ ] Transcript: markdown/code, safe text, tool calls, full tool results, sources, artifact downloads, long messages, scroll/selection preservation
- [ ] Observatory: 3 lenses, subagents, execution graph, receipts, costs (settled vs provider measured), token coverage, context, budgets, recovery
- [ ] Sessions/projects: create, rename, pin, archive, export; project edit/files/documents
- [ ] Knowledge/Goals: search/import/preview/archive; goals/work progress/scheduling
- [ ] Models/auth: native provider catalog, model pool, token budget, reasoning, temperature; API key and independent OAuth flows
- [ ] Accessibility/offline: IME, keyboard, focus, reduce motion, 5×2×13 screenshots, local fonts/CSP/wheel assets

## Engineering choice

React 19, TypeScript strict, Vite (packaged static SPA, no Next.js server), native form controls and domain-built Agent components. HeroUI/Tailwind were removed because only one save button used them; the native button submits the same form. Python and command contracts are not rewritten merely to introduce React. No new SSE endpoint until there is a justified event cursor and crash-replay specification.
