"""Local Ollama adapter using the documented /api/chat endpoint."""

from __future__ import annotations

import json
import socket
from urllib import error, request

from ..models import ContextTruncated, ModelRequest, ModelResult, ProviderStatus


class OllamaProvider:
    provider_id = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 180.0,
        keep_alive: str = "5m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive

    def _json_request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        raw = None
        for attempt in range(2):
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = response.read()
                break
            except error.URLError as exc:
                # Retry only failures that prove no HTTP request was accepted:
                # connection refused / DNS resolution. Timeouts and other
                # post-dispatch ambiguity remain single-shot and become UNKNOWN
                # at the Runtime boundary.
                reason=getattr(exc,"reason",None)
                pre_dispatch=isinstance(reason,(ConnectionRefusedError,socket.gaierror))
                if attempt==0 and pre_dispatch:
                    continue
                raise RuntimeError(f"Ollama request failed: {exc}") from exc
        if raw is None:
            raise RuntimeError("Ollama request produced no response bytes")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("Ollama response must be a JSON object")
        return value

    def check(self) -> ProviderStatus:
        try:
            value = self._json_request("GET", "/api/tags")
            models = [
                item.get("name")
                for item in value.get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return ProviderStatus(self.provider_id, True, auth_type="none", details={"models": models})
        except Exception as exc:
            return ProviderStatus(self.provider_id, False, auth_type="none", details={"error": str(exc)})

    def invoke(self, model_request: ModelRequest) -> ModelResult:
        payload: dict = {
            "model": model_request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in model_request.messages
            ],
            "format": model_request.response_schema,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_predict": model_request.max_output_tokens,
                "temperature": float(model_request.temperature),
                **({"num_ctx": model_request.num_ctx} if model_request.num_ctx is not None else {}),
            },
        }
        if model_request.thinking is not None:
            payload["think"] = model_request.thinking

        value = self._json_request("POST", "/api/chat", payload)
        message = value.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError("Ollama response is missing message.content")
        usage = {"model_calls":1}
        for source,meter in [("prompt_eval_count","input_tokens"),("eval_count","output_tokens")]:
            if type(value.get(source)) is int and value[source]>=0:usage[meter]=value[source]
        total_duration = value.get("total_duration")
        if type(total_duration) is int and total_duration >= 0:
            usage["model_duration_ns"] = total_duration
        used=value.get("prompt_eval_count")
        if (
            model_request.num_ctx is not None
            and type(used) is int
            and used >= model_request.num_ctx - 16
        ):
            raise ContextTruncated(
                f"prompt_eval_count={used} reached configured num_ctx={model_request.num_ctx}",
                usage=usage,
                raw=value,
            )
        return ModelResult(
            text=message["content"],
            usage=usage,
            raw=value,
            response_id=None,
        )
