# Security & Privacy Boundary

Myth is local-first. Remote model providers are explicit choices; tool authority remains local.

## Never committed

- `.runtime/`, SQLite databases, `.env*`, private keys and local workspaces are gitignored.
- Production prompts, user documents, OAuth tokens, API keys and private traces must not be committed as fixtures.
- If a secret is ever committed, rotate it; deleting a later Git revision is not sufficient.

## File capability boundary

- User files must be explicitly present in the Agent Run's `allowed_files` set.
- Model-proposed paths are resolved and checked against that set before any durable Tool Intent is created.
- The current executor exposes only `file.patch_exact`; there is no arbitrary shell.
- Changes occur in Myth's managed workspace. The original user file is not silently overwritten.
- A Ticket is launch authority, not proof of success. Unknown effects are not blindly replayed.

## Model boundary

- **Ollama:** requests go to the configured local endpoint. Use this for content that must remain local.
- **OpenAI API key:** `OPENAI_API_KEY` is read at call time and is never persisted by Myth.
- **Pi OAuth / ChatGPT subscription:** Myth does not read or write Pi's `auth.json`. It asks Pi for a refreshed bearer token via `pi auth print-bearer-token`; Pi remains the credential owner.
- Bearer/API tokens are used only for the outbound request and are not inserted into ModelResult, durable receipts, object-store artifacts, events or Web responses.
- A remote provider receives the selected model request content by definition.

## Agent authority boundary

Model output is untrusted proposal data.

A model cannot directly:

- execute a tool;
- widen file scope;
- increase budget;
- turn a Ticket into a Receipt;
- mark a Run successful.

A `request_completion` decision is accepted only after AgentVerifier checks cited durable evidence and the current managed artifact digest.

## Web boundary

- `myth web` accepts loopback hosts only: `127.0.0.1`, `localhost`, or `::1`.
- P3 has no CORS endpoint, credential endpoint, arbitrary file browser or shell endpoint.
- Do not expose the local server through a tunnel/reverse proxy without adding authentication, CSRF protection and a stronger multi-user authorization model first.
