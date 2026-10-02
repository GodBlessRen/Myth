"""OpenAI Responses adapter with either env API-key or Pi-managed OAuth auth.

For Pi OAuth, Myth deliberately does not read or write Pi's auth.json.  It uses
Pi's public `auth print-bearer-token` CLI, which performs refresh under Pi's own
credential lock.  The bearer token exists only in this process long enough to
construct the Authorization header and is never returned in ModelResult/raw.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import shutil
import subprocess
from typing import Callable
from urllib import error, request

from ..models import ModelRequest, ModelResult, ProviderStatus


TokenSupplier = Callable[[], str]


def _extract_output_text(value: dict) -> str:
    chunks: list[str] = []
    for item in value.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if not chunks:
        raise RuntimeError("OpenAI response did not contain output_text")
    return "".join(chunks)


@dataclass(frozen=True)
class PiBearerTokenSource:
    pi_command: str = "pi"
    provider: str = "openai"
    min_expiry: str = "10m"
    timeout: float = 30.0

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.pi_command, *args],
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Pi CLI was not found. Install @earendil-works/pi-coding-agent first."
            ) from exc

    def check(self) -> ProviderStatus:
        if shutil.which(self.pi_command) is None and os.path.sep not in self.pi_command:
            return ProviderStatus("pi-openai", False, auth_type="oauth", details={"error": "Pi CLI not found"})
        result = self._run(["auth", "check", "--provider", self.provider, "--json"])
        if result.returncode != 0:
            return ProviderStatus(
                "pi-openai", False, auth_type="oauth", details={"error": result.stderr.strip() or "Pi auth check failed"}
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            return ProviderStatus(
                "pi-openai", False, auth_type="oauth", details={"error": "Pi auth check returned non-JSON output"}
            )
        ready = isinstance(value, dict) and value.get("status") == "ready" and value.get("authType") == "oauth"
        return ProviderStatus("pi-openai", ready, auth_type="oauth", details=value if isinstance(value, dict) else None)

    def token(self) -> str:
        result = self._run(
            [
                "auth",
                "print-bearer-token",
                "--provider",
                self.provider,
                "--min-expiry",
                self.min_expiry,
            ]
        )
        if result.returncode != 0:
            message = result.stderr.strip() or "Pi could not resolve an OAuth bearer token"
            raise RuntimeError(
                f"{message}. Start Pi, run /login openai, and choose Sign in with ChatGPT."
            )
        token = result.stdout.strip()
        if not token or any(ch.isspace() for ch in token):
            raise RuntimeError("Pi returned an invalid bearer token")
        return token


class OpenAIResponsesProvider:
    """Direct Responses API transport. Authentication is injected, not persisted."""

    def __init__(
        self,
        *,
        provider_id: str,
        token_supplier: TokenSupplier,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 180.0,
        subscription_token: bool = False,
        auth_type: str = "api_key",
        status_check: Callable[[], ProviderStatus] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._token_supplier = token_supplier
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.subscription_token = subscription_token
        self.auth_type = auth_type
        self._status_check = status_check

    def check(self) -> ProviderStatus:
        if self._status_check is not None:
            return self._status_check()
        try:
            token = self._token_supplier()
        except Exception as exc:
            return ProviderStatus(self.provider_id, False, auth_type=self.auth_type, details={"error": str(exc)})
        return ProviderStatus(self.provider_id, bool(token), auth_type=self.auth_type, details={})

    def invoke(self, model_request: ModelRequest) -> ModelResult:
        token = self._token_supplier()
        # Pi's upstream OpenAI adapter intentionally omits max_output_tokens and
        # temperature for Sign in with ChatGPT access tokens; preserve that
        # compatibility boundary here instead of assuming API-key semantics.
        payload: dict = {
            "model": model_request.model,
            "input": [
                {"role": "developer" if message.role == "system" else message.role, "content": message.content}
                for message in model_request.messages
            ],
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "myth_step_decision",
                    "schema": model_request.response_schema,
                    "strict": False,
                }
            },
        }
        if not self.subscription_token:
            payload["max_output_tokens"] = max(model_request.max_output_tokens, 16)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/responses",
            data=body,
            method="POST",
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": "application/json",
                "user-agent": "myth-runtime/0.2",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses request failed ({exc.code}): {detail[:1000]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI Responses request failed: {exc}") from exc
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("OpenAI response must be a JSON object")
        if value.get("status") not in {None, "completed"}:
            raise RuntimeError(f"OpenAI response ended with status={value.get('status')!r}")
        usage_value = value.get("usage") if isinstance(value.get("usage"), dict) else {}
        usage = {
            "model_calls": 1,
            "input_tokens": int(usage_value.get("input_tokens") or 0),
            "output_tokens": int(usage_value.get("output_tokens") or 0),
        }
        # Responses reports prompt-cache reuse inside input_tokens_details.
        # Keep these as observability meters only: cached tokens are already
        # included in input_tokens and must not be double-counted in budgets.
        input_details = (
            usage_value.get("input_tokens_details")
            if isinstance(usage_value.get("input_tokens_details"), dict)
            else {}
        )
        cached_tokens = input_details.get("cached_tokens")
        if type(cached_tokens) is int and cached_tokens >= 0:
            usage["cached_input_tokens"] = cached_tokens
        cache_write_tokens = input_details.get("cache_write_tokens")
        if type(cache_write_tokens) is int and cache_write_tokens >= 0:
            usage["cache_write_input_tokens"] = cache_write_tokens
        return ModelResult(
            text=_extract_output_text(value),
            usage=usage,
            raw=value,
            response_id=value.get("id") if isinstance(value.get("id"), str) else None,
        )


class PiOpenAIProvider(OpenAIResponsesProvider):
    provider_id = "pi-openai"

    def __init__(self, pi_command: str = "pi", timeout: float = 180.0) -> None:
        source = PiBearerTokenSource(pi_command=pi_command)
        self.token_source = source
        super().__init__(
            provider_id=self.provider_id,
            token_supplier=source.token,
            timeout=timeout,
            subscription_token=True,
            auth_type="oauth",
            status_check=source.check,
        )


class OpenAIApiKeyProvider(OpenAIResponsesProvider):
    provider_id = "openai"

    def __init__(self, env_var: str = "OPENAI_API_KEY", timeout: float = 180.0) -> None:
        def token() -> str:
            value = os.environ.get(env_var, "").strip()
            if not value:
                raise RuntimeError(f"{env_var} is not set")
            return value

        super().__init__(
            provider_id=self.provider_id,
            token_supplier=token,
            timeout=timeout,
            subscription_token=False,
            auth_type="api_key",
        )
