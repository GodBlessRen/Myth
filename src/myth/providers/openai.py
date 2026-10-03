"""OpenAI Responses 与 ChatGPT 计划的传输适配器。
共用统一请求合同，凭据通过调用时供应函数取得；解析 JSON/SSE 的完成事实后返回 ModelResult，凭据不写入 raw 或 Runtime 对象。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable
from urllib import error, parse, request

from .. import __version__
from ..auth.chatgpt import ChatGPTAuthManager
from ..auth.transport import (
    MAX_RESPONSE_BYTES, open_credential_request, read_bounded,
    public_error_code, redact_response,
)
from ..models import ModelRequest, ModelResult, ProviderStatus, ProviderKnownFailure, ProviderUnavailable
from ..network_recovery import is_pre_dispatch_disconnect


# TokenSupplier：短期访问 token 的传输回调类型；调用/返回内容不能持久记录。
TokenSupplier = Callable[[], str]


# 按 SSE 空行分帧，支持多行 data；有限 read 防止单行/心跳流耗尽内存，末尾无空行也能解析。
def _sse_events(response, *, deadline=None):
    fields = []
    frame_size = 0
    total_size = 0
    while True:
        raw_line = response.readline(2 * 1024 * 1024 + 1)
        if deadline is not None and time.monotonic() > deadline:
            raise RuntimeError("OpenAI Responses stream exceeded its deadline")
        if not raw_line:
            if fields:
                yield "\n".join(fields), frame_size
            return
        frame_size += len(raw_line)
        total_size += len(raw_line)
        if frame_size > 2 * 1024 * 1024 or total_size > MAX_RESPONSE_BYTES:
            raise RuntimeError("OpenAI Responses stream exceeds the byte limit")
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if not line:
            if fields:
                yield "\n".join(fields), frame_size
            fields = []
            frame_size = 0
        elif line.startswith("data:"):
            fields.append(line[5:].lstrip(" "))


# 从 Responses 完成对象提取 output_text；没有有效文本显式失败，不把 thinking/未知字段当回答。
def _extract_output_text(value: dict) -> str:
    chunks: list[str] = []
    for item in value.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                chunks.append(content["text"])
    if not chunks:
        raise RuntimeError("OpenAI response did not contain output_text")
    return "".join(chunks)


# 投影供应商实际用量及可选缓存量；缺字段保持未知，不结算为真实零成本。
def _usage(value: dict) -> dict[str, int]:
    usage_value = value.get("usage") if isinstance(value.get("usage"), dict) else {}
    result = {
        "model_calls": 1,
    }
    # 缺失用量保留未知；bool/负数/字符串不能冒充供应商计量。
    for meter in ("input_tokens", "output_tokens"):
        if type(usage_value.get(meter)) is int and usage_value[meter] >= 0:
            result[meter] = usage_value[meter]
    input_details = (
        usage_value.get("input_tokens_details")
        if isinstance(usage_value.get("input_tokens_details"), dict)
        else {}
    )
    cached_tokens = input_details.get("cached_tokens")
    if type(cached_tokens) is int and cached_tokens >= 0:
        result["cached_input_tokens"] = cached_tokens
    return result


# Responses 传输基类；token 延迟获取，普通 API 与计划 SSE 共用结果合同，不修改业务状态。
class OpenAIResponsesProvider:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
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
        # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
        self.provider_id = provider_id
        # _token_supplier：短期 token 获取函数；只在传输边界调用，返回值不得记录。
        self._token_supplier = token_supplier
        # base_url：明确供应商/服务入口；产品设置校验允许范围，传输层使用该固定地址。
        self.base_url = base_url.rstrip("/")
        endpoint = parse.urlparse(self.base_url)
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username
                or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("OpenAI credentials require an HTTPS endpoint without URL credentials")
        if chatgpt_plan and self.base_url != "https://api.openai.com/v1":
            raise ValueError("ChatGPT plan credentials require the official Responses endpoint")
        # timeout：一次网络/操作等待的上限，单位秒；超时不能证明远端未执行。
        self.timeout = timeout
        # chatgpt_plan：ChatGPT 计划模型传输适配器；实际请求仍通过模型 Ticket。
        self.chatgpt_plan = chatgpt_plan
        # auth_type：认证方式描述；不携带凭据内容。
        self.auth_type = auth_type
        # _status_check：供应商可公开连接状态函数；不执行业务模型请求。
        self._status_check = status_check

    # 观察供应商认证/服务是否可用；返回状态而不签发模型 Ticket。
    def check(self) -> ProviderStatus:
        if self._status_check is not None:
            return self._status_check()
        try:
            token = self._token_supplier()
        except Exception:
            return ProviderStatus(
                self.provider_id,
                False,
                auth_type=self.auth_type,
                details={"error": "OpenAI credential is unavailable"},
            )
        return ProviderStatus(
            self.provider_id, bool(token), auth_type=self.auth_type, details={}
        )

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, model_request: ModelRequest) -> ModelResult:
        started = time.monotonic()
        try:
            token = self._token_supplier()
            if not isinstance(token, str) or not token:
                raise RuntimeError("missing credential")
        except Exception:
            # 本地认证拒绝发生在推理请求派发前；无需 UNKNOWN，也不能泄露底层异常。
            raise ProviderKnownFailure("OpenAI credential is unavailable", usage={
                "model_calls": 0, "input_tokens": 0, "output_tokens": 0,
            }, raw={"status": "credential_unavailable"}) from None
        payload: dict = {
            "model": model_request.model,
            "input": [
                {
                    "role": "developer" if message.role == "system" else message.role,
                    "content": message.content,
                }
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
        # 两条路径都按流消费；决定只有 terminal completion 后才能交 Runtime。
        payload["stream"] = True
        if not self.chatgpt_plan:
            payload["max_output_tokens"] = max(model_request.max_output_tokens, 16)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/responses",
            data=body,
            method="POST",
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": (
                    "text/event-stream"
                ),
                "user-agent": f"myth-runtime/{__version__}",
            },
        )
        response_started = False
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                response_started = True
                # 明确 JSON 响应兼容固定测试/网关；OAuth 仍强制流式完成合同。
                content_type = getattr(response, "headers", {}).get("Content-Type", "")
                if self.chatgpt_plan or "text/event-stream" in content_type:
                    value, streamed_text, first_token_ms = self._read_stream(response, started, self.timeout)
                else:
                    raw = read_bounded(response)
                    value = json.loads(raw.decode("utf-8"))
                    streamed_text = None
                    first_token_ms = None
        except error.HTTPError as exc:
            with exc:
                raw = read_bounded(exc)
            detail = "request rejected"
            try:
                body_value = json.loads(raw.decode("utf-8"))
                if isinstance(body_value, dict):
                    error_value = body_value.get("error")
                    if isinstance(error_value, dict):
                        detail = public_error_code(error_value.get("code"), detail)
            except Exception:
                pass
            message = f"OpenAI Responses request failed ({exc.code}): {detail}"
            if exc.code in {400, 401, 403, 404, 422, 429}:
                raise ProviderKnownFailure(message, usage={"model_calls": 1}, raw={
                    "http_status": exc.code, "error": {"code": detail},
                }) from None
            raise RuntimeError(message) from None
        except error.URLError as exc:
            # 仅 HTTP 尚未建立且原因证明未派发时允许后续另准入；流内错误仍是 UNKNOWN。
            if not response_started and is_pre_dispatch_disconnect(exc.reason):
                raise ProviderUnavailable() from None
            raise RuntimeError(
                "OpenAI Responses request failed before completion"
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OpenAI Responses returned malformed data") from None

        if not isinstance(value, dict):
            raise RuntimeError("OpenAI response must be a JSON object")
        if value.get("status") not in {None, "completed"}:
            raise RuntimeError(
                "OpenAI response ended without successful completion"
            )
        try:
            output_text = _extract_output_text(value)
        except RuntimeError:
            if not streamed_text:
                raise
            output_text = streamed_text
        usage = _usage(value)
        if first_token_ms is not None:
            usage["time_to_first_token_ms"] = first_token_ms
        # 不保存服务端回显的请求头/凭据/未知元数据，只留结果与用量证据。
        safe_raw = redact_response({k: value[k] for k in ("id", "status", "output", "usage") if k in value}, token)
        return ModelResult(
            text=redact_response(output_text, token),
            usage=usage,
            raw=safe_raw,
            response_id=safe_raw.get("id") if isinstance(safe_raw.get("id"), str) else None,
        )

    # 逐 SSE data 消费文本增量，只有 response.completed 才返回；失败/中断不能伪造完整响应。
    @staticmethod
    def _read_stream(response, started=None, timeout=180.0):
        completed = None
        text_chunks = []
        first_token_ms = None
        started = time.monotonic() if started is None else started
        total_bytes = 0
        # 每事件/整次流都有字节上限；只保留数据字段，不信任服务端自定义错误描述。
        for data, size in _sse_events(response, deadline=started + timeout):
            if time.monotonic() - started > timeout:
                raise RuntimeError("OpenAI Responses stream exceeded its deadline")
            total_bytes += size
            if total_bytes > MAX_RESPONSE_BYTES:
                raise RuntimeError("OpenAI Responses stream exceeds the byte limit")
            if not data or data == "[DONE]":
                continue
            event_value = json.loads(data)
            if not isinstance(event_value, dict):
                continue
            event_type = event_value.get("type")
            if event_type == "response.output_text.delta" and isinstance(
                event_value.get("delta"), str
            ):
                if event_value["delta"] and first_token_ms is None:
                    first_token_ms = max(0, int((time.monotonic() - started) * 1000))
                text_chunks.append(event_value["delta"])
            elif event_type == "response.completed" and isinstance(
                event_value.get("response"), dict
            ):
                completed = event_value["response"]
                break
            elif event_type in {"response.failed", "response.incomplete"}:
                response_value = (
                    event_value.get("response")
                    if isinstance(event_value.get("response"), dict)
                    else {}
                )
                error_value = (
                    response_value.get("error")
                    if isinstance(response_value.get("error"), dict)
                    else {}
                )
                code = public_error_code(error_value.get("code"), event_type)
                raise ProviderKnownFailure(f"OpenAI Responses stream failed: {code}",
                    usage=_usage(response_value), raw={"status": event_type, "error": {"code": code}})
            elif event_type == "error":
                raise RuntimeError("OpenAI Responses stream reported an error")
        if completed is None:
            raise RuntimeError(
                "OpenAI Responses stream ended without response.completed"
            )
        return completed, "".join(text_chunks), first_token_ms


# Myth 自有 OAuth 计划适配器；认证管理器供给短期 token，模型目录只返回可公开数据。
class ChatGPTPlanProvider(OpenAIResponsesProvider):
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id = "chatgpt"

    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, root: str | Path, timeout: float = 180.0) -> None:
        # auth：认证管理对象；凭据不进入 Runtime 事件或对象。
        self.auth = ChatGPTAuthManager(root, timeout=min(timeout, 30.0))

        # 在 OAuth 状态可用后读取可公开模型目录；请求错误返回未 ready，不泄露 token。
        def status_check() -> ProviderStatus:
            status = self.auth.status()
            details = status.serializable()
            if not status.ready:
                return ProviderStatus(
                    self.provider_id, False, auth_type="oauth", details=details
                )
            try:
                models = self.auth.list_models()
            except Exception:
                details["error"] = "ChatGPT model catalog is unavailable"
                return ProviderStatus(
                    self.provider_id, False, auth_type="oauth", details=details
                )
            details["models"] = [item["slug"] for item in models]
            details["model_details"] = models
            return ProviderStatus(
                self.provider_id, True, auth_type="oauth", details=details
            )

        super().__init__(
            provider_id=self.provider_id,
            token_supplier=self.auth.access_token,
            timeout=timeout,
            chatgpt_plan=True,
            auth_type="oauth",
            status_check=status_check,
        )


# 环境变量凭据适配器；每次请求读取 key，不保存或公开它。
class OpenAIApiKeyProvider(OpenAIResponsesProvider):
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id = "openai"

    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, env_var: str = "OPENAI_API_KEY", timeout: float = 180.0) -> None:
        # 调用时从指定环境变量读取 API key；缺失显式失败，秘钥不持久化。
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
