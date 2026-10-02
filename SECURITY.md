# Security & Privacy Boundary

Myth is local-first, but P2 can intentionally call a remote model provider.

## Never committed

- `.runtime/`, SQLite databases, `.env*`, private keys and local workspaces are gitignored.
- Production prompts, user documents, OAuth tokens, API keys and raw private traces must not be committed as fixtures.
- If a secret is ever committed, rotate it; deleting a later Git revision is not sufficient.

## P1 file boundary

- P1 imports source bytes into a managed workspace and does not silently overwrite the original user file.
- The executor exposes one exact text-patch capability; there is no arbitrary shell.
- A Ticket is launch authority, not proof of success. Unknown effects are not blindly replayed.

## P2 model boundary

- **Ollama:** requests go to the configured local endpoint. This is the preferred path for data that must stay local.
- **OpenAI API key:** the key is read from `OPENAI_API_KEY` at call time and is never persisted by Myth.
- **Pi OAuth / ChatGPT subscription:** Myth does not read or write Pi's `auth.json`. It asks the installed Pi CLI for a refreshed bearer token using `pi auth print-bearer-token`; Pi remains the credential owner.
- Bearer/API tokens are used only in the HTTP Authorization header and are never inserted into ModelResult, durable receipts, object-store artifacts, events or logs.
- A remote provider receives the model request content by definition. Do not choose a remote provider for material that must not leave the machine.

## Authority boundary

Model output is untrusted proposal data. A `tool_call` StepDecision cannot directly execute a tool, widen file scope, change budget/permissions, or mark a Run successful.
