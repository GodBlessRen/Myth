"""OpenAI Responses providers with API-key or Myth-owned ChatGPT OAuth authentication.

OAuth credentials never enter Runtime SQLite/events/object storage or ModelResult.raw.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable
from urllib import error, request

from ..auth.chatgpt import ChatGPTAuthManager
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


def _usage(value: dict) -> dict[str, int]:
    usage_value = value.get("usage") if isinstance(value.get("usage"), dict) else {}
    result = {
        "model_calls": 1,
        "input_tokens": int(usage_value.get("input_tokens") or 0),
        "output_tokens": int(usage_value.get("output_tokens") or 0),
    }
    input_details = usage_value.get("input_tokens_details") if isinstance(usage_value.get("input_tokens_details"), dict) else {}
    cached_tokens = input_details.get("cached_tokens")
    if type(cached_tokens) is int and cached_tokens >= 0:
        result["cached_input_tokens"] = cached_tokens
    return result


class OpenAIResponsesProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        token_supplier: TokenSupplier,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 180.0,
        chatgpt_plan: bool = False,
        auth_type: str = "api_key",
        status_check: Callable[[], ProviderStatus] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._token_supplier = token_supplier
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.chatgpt_plan = chatgpt_plan
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
        if self.chatgpt_plan:
            payload["stream"] = True
        else:
            payload["max_output_tokens"] = max(model_request.max_output_tokens, 16)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/responses",
            data=body,
            method="POST",
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": "text/event-stream" if self.chatgpt_plan else "application/json",
                "user-agent": "myth-runtime/0.19",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                if self.chatgpt_plan:
                    value, streamed_text = self._read_stream(response)
                else:
                    raw = response.read()
                    value = json.loads(raw.decode("utf-8"))
                    streamed_text = None
        except error.HTTPError as exc:
            raw = exc.read()
            detail = "request rejected"
            try:
                body_value = json.loads(raw.decode("utf-8"))
                if isinstance(body_value, dict):
                    error_value = body_value.get("error")
                    if isinstance(error_value, dict):
                        detail = str(error_value.get("code") or error_value.get("message") or detail)
                    elif isinstance(body_value.get("detail"), str):
                        detail = body_value["detail"]
            except Exception:
                pass
            raise RuntimeError(f"OpenAI Responses request failed ({exc.code}): {detail[:300]}") from exc
        except error.URLError as exc:
            raise RuntimeError("OpenAI Responses request failed before completion") from exc

        if not isinstance(value, dict):
            raise RuntimeError("OpenAI response must be a JSON object")
        if value.get("status") not in {None, "completed"}:
            raise RuntimeError(f"OpenAI response ended with status={value.get('status')!r}")
        try:
            output_text = _extract_output_text(value)
        except RuntimeError:
            if not streamed_text:
                raise
            output_text = streamed_text
        return ModelResult(
            text=output_text,
            usage=_usage(value),
            raw=value,
            response_id=value.get("id") if isinstance(value.get("id"), str) else None,
        )

    @staticmethod
    def _read_stream(response):
        completed = None
        text_chunks = []
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="strict").strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event_value = json.loads(data)
            if not isinstance(event_value, dict):
                continue
            event_type = event_value.get("type")
            if event_type == "response.output_text.delta" and isinstance(event_value.get("delta"), str):
                text_chunks.append(event_value["delta"])
            elif event_type == "response.completed" and isinstance(event_value.get("response"), dict):
                completed = event_value["response"]
            elif event_type in {"response.failed", "response.incomplete"}:
                response_value = event_value.get("response") if isinstance(event_value.get("response"), dict) else {}
                error_value = response_value.get("error") if isinstance(response_value.get("error"), dict) else {}
                code = error_value.get("code") or event_type
                raise RuntimeError(f"OpenAI Responses stream failed: {code}")
        if completed is None:
            raise RuntimeError("OpenAI Responses stream ended without response.completed")
        return completed, "".join(text_chunks)


class ChatGPTPlanProvider(OpenAIResponsesProvider):
    provider_id = "chatgpt"

    def __init__(self, root: str | Path, timeout: float = 180.0) -> None:
        self.auth = ChatGPTAuthManager(root, timeout=min(timeout, 30.0))

        def status_check() -> ProviderStatus:
            status = self.auth.status()
            details = status.serializable()
            if not status.ready:
                return ProviderStatus(self.provider_id, False, auth_type="oauth", details=details)
            try:
                models = self.auth.list_models()
            except Exception as exc:
                details["error"] = str(exc)
                return ProviderStatus(self.provider_id, False, auth_type="oauth", details=details)
            details["models"] = [item["slug"] for item in models]
            details["model_details"] = models
            return ProviderStatus(self.provider_id, True, auth_type="oauth", details=details)

        super().__init__(
            provider_id=self.provider_id,
            token_supplier=self.auth.access_token,
            timeout=timeout,
            chatgpt_plan=True,
            auth_type="oauth",
            status_check=status_check,
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
            chatgpt_plan=False,
            auth_type="api_key",
        )
