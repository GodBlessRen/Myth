"""Claude Messages 与 Kimi Chat Completions 的外圈传输。

固定 HTTPS 凭据接收端，复用禁止重定向的传输。收到完整但不合合同的响应记为
已知失败；发出请求后断连保持 UNKNOWN，由 DecisionRuntime 管理收据与恢复。
"""

from __future__ import annotations

import json
from urllib import request, error

from ..auth.transport import open_credential_request, read_bounded, redact_response
from ..model_capabilities import model_capability, reasoning_capability
from ..models import ModelResult, ProviderStatus, ProviderKnownFailure, ProviderUnavailable
from ..network_recovery import is_pre_dispatch_disconnect


class MessagesProvider:
    """两种消息协议共用受限 HTTP 外壳；厂商差异只存在于请求/结果映射。"""

    def __init__(self, provider_id, token_supplier, timeout=180.0):
        """供应商 ID 来自装配白名单；凭据延迟读取，不进入实例公开状态。"""
        if provider_id not in {"anthropic", "kimi"}:
            raise ValueError("unsupported messages provider")
        # provider_id：Runtime 固定的供应商身份。
        self.provider_id = provider_id
        # _token_supplier：系统凭据读取端口；绝不记录返回值。
        self._token_supplier = token_supplier
        # timeout：网络等待秒数，不代表取消远端生成。
        self.timeout = timeout
        # base_url：固定接收端，不能用用户文本替换以转发凭据。
        self.base_url = "https://api.anthropic.com/v1" if provider_id == "anthropic" else "https://api.moonshot.ai/v1"

    def _request(self, path, payload=None):
        """只在明确连接前故障报告零派发；响应正文与异常不得泄露密钥。"""
        try:
            token = self._token_supplier()
            if not isinstance(token, str) or not token:
                raise ValueError("missing key")
        except Exception:
            raise ProviderKnownFailure("Provider credential unavailable", usage={
                "model_calls": 0, "input_tokens": 0, "output_tokens": 0}) from None
        headers = {"Content-Type": "application/json"}
        if self.provider_id == "anthropic":
            headers.update({"x-api-key": token, "anthropic-version": "2023-06-01"})
        else:
            headers["Authorization"] = "Bearer " + token
        req = request.Request(self.base_url + path, headers=headers,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None)
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                raw = read_bounded(response)
        except error.HTTPError as exc:
            # 4xx 明确拒绝仍不伪造 Token；5xx 可能已执行，保留 UNKNOWN。
            if 400 <= exc.code < 500:
                raise ProviderKnownFailure(f"Provider rejected request (HTTP {exc.code})",
                    usage={"model_calls": int(payload is not None)}, raw={"http_status": exc.code}) from None
            raise RuntimeError(f"Provider outcome unknown (HTTP {exc.code})") from None
        except error.URLError as exc:
            if is_pre_dispatch_disconnect(exc.reason):
                raise ProviderUnavailable() from None
            raise RuntimeError("Provider transport outcome unknown") from None
        except OSError:
            raise RuntimeError("Provider transport outcome unknown") from None
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProviderKnownFailure("Provider returned invalid JSON", usage={"model_calls": int(payload is not None)}) from None
        if not isinstance(value, dict):
            raise ProviderKnownFailure("Provider returned invalid object", usage={"model_calls": int(payload is not None)})
        return redact_response(value, token)

    def check(self):
        """只读模型目录；连通与认证成功不等于具体模型已通过生成验收。"""
        try:
            value = self._request("/models")
            models = [x["id"] for x in value.get("data", []) if isinstance(x, dict) and isinstance(x.get("id"), str)]
            if not models:
                raise ValueError("empty catalog")
            reasoning = reasoning_capability(kind="toggle", off=False) if self.provider_id == "kimi" else None
            return ProviderStatus(self.provider_id, True, "api_key", {
                "models": models, "model_capabilities": {m: model_capability(m, reasoning=reasoning) for m in models}})
        except Exception:
            return ProviderStatus(self.provider_id, False, "api_key", {"error": "模型目录检查失败，请检查连接与凭据。"})

    def invoke(self, model_request):
        """把统一结构化决定映射为厂商协议；只返回结果文本和计量，不保存隐藏推理。"""
        messages = [{"role": m.role, "content": m.content} for m in model_request.messages]
        if self.provider_id == "anthropic":
            # 首版使用强制单工具产出 JSON；与扩展 Thinking 不混用，避免隐式改变配置。
            if model_request.thinking not in (None, False, "none"):
                raise ProviderKnownFailure("Claude adapter currently supports default/disabled thinking only",
                    usage={"model_calls": 0, "input_tokens": 0, "output_tokens": 0})
            payload = {"model": model_request.model, "max_tokens": model_request.max_output_tokens,
                "temperature": model_request.temperature,
                "system": "\n".join(m["content"] for m in messages if m["role"] in {"system", "developer"}),
                "messages": [m for m in messages if m["role"] not in {"system", "developer"}],
                "tools": [{"name": "myth_decision", "description": "Return the required Myth decision.",
                           "input_schema": model_request.response_schema}],
                "tool_choice": {"type": "tool", "name": "myth_decision", "disable_parallel_tool_use": True}}
            value = self._request("/messages", payload)
            usage = self._usage(value.get("usage") or {})
            blocks = [x for x in value.get("content", []) if x.get("type") == "tool_use" and x.get("name") == "myth_decision"]
            if len(blocks) != 1 or value.get("stop_reason") != "tool_use":
                raise ProviderKnownFailure("Claude did not return a complete decision", usage=usage)
            text = json.dumps(blocks[0].get("input"), ensure_ascii=False)
        else:
            messages.insert(0, {"role": "system", "content": "Return only JSON matching this schema: " + json.dumps(model_request.response_schema)})
            payload = {"model": model_request.model, "messages": messages, "max_tokens": model_request.max_output_tokens,
                       "temperature": model_request.temperature,
                       "response_format": {"type": "json_object"}, "stream": False}
            if model_request.thinking is not None:
                if model_request.thinking not in (True, False, "enabled", "disabled"):
                    raise ProviderKnownFailure("Kimi thinking must be enabled/disabled", usage={"model_calls": 0, "input_tokens": 0, "output_tokens": 0})
                payload["thinking"] = {"type": "enabled" if model_request.thinking in (True, "enabled") else "disabled"}
            value = self._request("/chat/completions", payload)
            usage = self._usage(value.get("usage") or {})
            choices = value.get("choices") or []
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise ProviderKnownFailure("Kimi did not return a complete decision", usage=usage)
            text = (choices[0].get("message") or {}).get("content")
            if not isinstance(text, str):
                raise ProviderKnownFailure("Kimi returned no decision text", usage=usage)
        return ModelResult(text, usage, {"id": value.get("id"), "usage": usage, "text": text}, value.get("id"))

    def _usage(self, raw):
        """统一各家输入/输出与缓存口径；缺字段留空，Claude 输入包含缓存读写。"""
        usage = {"model_calls": 1}
        fields = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
                  "cache_read_input_tokens": "cached_input_tokens", "cache_creation_input_tokens": "cache_write_input_tokens"}
        if self.provider_id == "kimi":
            fields = {"prompt_tokens": "input_tokens", "completion_tokens": "output_tokens", "cached_tokens": "cached_input_tokens"}
        for source, target in fields.items():
            if type(raw.get(source)) is int and raw[source] >= 0:
                usage[target] = raw[source]
        if self.provider_id == "anthropic" and "input_tokens" in usage:
            usage["input_tokens"] += usage.get("cached_input_tokens", 0) + usage.get("cache_write_input_tokens", 0)
        return usage
