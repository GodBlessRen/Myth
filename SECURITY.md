# Security & Privacy Boundary

Myth v0.1 is intentionally local-first and network-free.

- `.runtime/`, SQLite databases, `.env*`, private keys, and local workspaces are gitignored.
- P1 does not send source files, traces, prompts, or artifacts to any remote service.
- P1 imports a source file into a managed workspace and never silently overwrites the original user file.
- The executor exposes one exact text-patch capability; there is no arbitrary shell or subprocess tool surface.
- Receipt/evidence records use digests and local references. Do not commit production traces or user documents as test fixtures.
- A future model adapter must use secret references/configuration outside committed source, must not log credentials, and must route model calls through the same Runtime budget/receipt path.

Private repository visibility reduces accidental exposure but is not a substitute for secret hygiene. Repository history should still be treated as durable: if a secret is ever committed, rotate it rather than relying only on a later deletion.
