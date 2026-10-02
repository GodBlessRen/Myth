# Security & Privacy Boundary

Myth is local-first. Remote model providers are explicit choices; tool authority remains local.

## Never committed

- `.runtime/`, SQLite databases, `.env*`, private keys and local workspaces are gitignored.
- Production prompts, user documents, OAuth tokens, API keys and private traces must not be committed as fixtures.
- If a secret is ever committed, rotate it; deleting a later Git revision is not sufficient.

## File capability boundary

- User files must be explicitly present in the Agent Run's `allowed_files` set.
- Model-proposed paths are resolved and checked against that set before any durable Tool Intent is created.
- The current executor exposes managed `file.read` and `file.patch_exact`; there is no arbitrary shell.
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

A `request_completion` decision is accepted only after the independent verifier checks the fixed complete goal manifest, all preserved files, cited own-run durable evidence and no remaining work. Downloads serve the fixed accepted object, not arbitrary paths or mutable workspace files.

## Web boundary

- `myth web` accepts loopback hosts only: `127.0.0.1`, `localhost`, or `::1`.
- Host/port validation rejects DNS-rebound hostnames. Mutations require JSON and a matching Origin when supplied. CSP, frame denial and text-only DOM rendering constrain the browser surface.
- There is no CORS endpoint, credential endpoint, arbitrary file browser or shell endpoint.
- The service is unauthenticated and trusts the local OS user. A hostile local process can still invoke it; loopback and Origin checks are not a multi-user authentication system.
- Do not expose the local server through a tunnel/reverse proxy without adding authentication, CSRF protection and a stronger multi-user authorization model first.
