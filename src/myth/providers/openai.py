"""OpenAI Responses 与 ChatGPT 计划的传输适配器。
共用统一请求合同，凭据通过调用时供应函数取得；解析 JSON/SSE 的完成事实后返回 ModelResult，凭据不写入 raw 或 Runtime 对象。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable
from urllib import error, request

from .. import __version__
from ..auth.chatgpt import ChatGPTAuthManager
from ..models import ModelRequest, ModelResult, ProviderStatus


# TokenSupplier：短期访问 token 的传输回调类型；调用/返回内容不能持久记录。
TokenSupplier = Callable[[], str]


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


# 投影供应商用量及可选缓存量；缺字段的当前兼容默认值不证明真实零成本。
def _usage(value: dict) -> dict[str, int]:
    usage_value = value.get("usage") if isinstance(value.get("usage"), dict) else {}
    result = {
        "model_calls": 1,
        "input_tokens": int(usage_value.get("input_tokens") or 0),
        "output_tokens": int(usage_value.get("output_tokens") or 0),
    }
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
        except Exception as exc:
            return ProviderStatus(
                self.provider_id,
                False,
                auth_type=self.auth_type,
                details={"error": str(exc)},
            )
        return ProviderStatus(
            self.provider_id, bool(token), auth_type=self.auth_type, details={}
        )

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, model_request: ModelRequest) -> ModelResult:
        token = self._token_supplier()
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
                "accept": (
                    "text/event-stream" if self.chatgpt_plan else "application/json"
                ),
                "user-agent": f"myth-runtime/{__version__}",
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
                        detail = str(
                            error_value.get("code")
                            or error_value.get("message")
                            or detail
                        )
                    elif isinstance(body_value.get("detail"), str):
                        detail = body_value["detail"]
            except Exception:
                pass
            raise RuntimeError(
                f"OpenAI Responses request failed ({exc.code}): {detail[:300]}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(
                "OpenAI Responses request failed before completion"
            ) from exc

        if not isinstance(value, dict):
            raise RuntimeError("OpenAI response must be a JSON object")
        if value.get("status") not in {None, "completed"}:
            raise RuntimeError(
                f"OpenAI response ended with status={value.get('status')!r}"
            )
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

    # 逐 SSE data 消费文本增量，只有 response.completed 才返回；失败/中断不能伪造完整响应。
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
            if event_type == "response.output_text.delta" and isinstance(
                event_value.get("delta"), str
            ):
                text_chunks.append(event_value["delta"])
            elif event_type == "response.completed" and isinstance(
                event_value.get("response"), dict
            ):
                completed = event_value["response"]
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
                code = error_value.get("code") or event_type
                raise RuntimeError(f"OpenAI Responses stream failed: {code}")
        if completed is None:
            raise RuntimeError(
                "OpenAI Responses stream ended without response.completed"
            )
        return completed, "".join(text_chunks)


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
            except Exception as exc:
                details["error"] = str(exc)
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
