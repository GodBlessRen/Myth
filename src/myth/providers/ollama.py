"""本机 Ollama HTTP 适配器。
把统一请求转换为 /api/chat，窗口与本地投影对齐；仅能证明未接收的连接错误可重试，派发后不明结果交回 Runtime 核对。"""

from __future__ import annotations

import json
from urllib import error, request, parse

from ..models import ContextTruncated, OutputTruncated, ModelRequest, ModelResult, ProviderStatus, ProviderKnownFailure, ProviderUnavailable
from ..network_recovery import is_pre_dispatch_disconnect
from ..auth.transport import open_credential_request, read_bounded


# Ollama HTTP 适配器；timeout 以秒计，num_ctx 与 ContextCompiler 窗口一致，结果不明不内部重发。
class OllamaProvider:
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id = "ollama"

    # 固定服务地址、超时和模型驻留选项；构造不推理，连接拒绝与派发后超时按不同恢复语义处理。
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 180.0,
        keep_alive: str = "5m",
    ) -> None:
        # base_url：明确供应商/服务入口；产品设置校验允许范围，传输层使用该固定地址。
        self.base_url = base_url.rstrip("/")
        endpoint = parse.urlparse(self.base_url)
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username
                or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("invalid Ollama endpoint")
        # timeout：一次网络/操作等待的上限，单位秒；超时不能证明远端未执行。
        self.timeout = timeout
        # keep_alive：Ollama 模型驻留选项；控制加载生命周期，不代表业务状态。
        self.keep_alive = keep_alive

    # 单次有界传输；派发前断连交 Runtime 持久退避，响应开始后异常保留不明结果。
    def _json_request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
        # 派发前断连有明确零派发证据才可退避；HTTP 拒绝是已知失败，响应开始后的异常保持未知。
        body = (
            None
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        response_started = False
        try:
            with open_credential_request(req, timeout=self.timeout) as response:
                response_started = True
                raw = read_bounded(response)
        except error.HTTPError as exc:
            exc.close()
            if exc.code in {400, 401, 403, 404, 422, 429}:
                raise ProviderKnownFailure(f"Ollama request rejected ({exc.code})",
                    usage={"model_calls": int(method == "POST")}, raw={"http_status": exc.code}) from None
            raise RuntimeError("Ollama request failed before completion") from None
        except error.URLError as exc:
            if not response_started and is_pre_dispatch_disconnect(exc.reason):
                raise ProviderUnavailable() from None
            raise RuntimeError("Ollama endpoint could not complete the request") from None
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Ollama returned malformed JSON") from None
        if not isinstance(value, dict):
            raise RuntimeError("Ollama response must be a JSON object")
        return value

    # 观察供应商认证/服务是否可用；返回状态而不签发模型 Ticket。
    def check(self) -> ProviderStatus:
        try:
            value = self._json_request("GET", "/api/tags")
            models = [
                item.get("name")
                for item in value.get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            return ProviderStatus(
                self.provider_id, True, auth_type="none", details={"models": models}
            )
        except Exception:
            return ProviderStatus(
                self.provider_id, False, auth_type="none", details={"error": "Ollama model catalog is unavailable"}
            )

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, model_request: ModelRequest) -> ModelResult:
        # 固定请求设置后派发；只采纳供应商明确报告的非负计量，并拒绝达到上下文上限的截断结果。
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
                **(
                    {"num_ctx": model_request.num_ctx}
                    if model_request.num_ctx is not None
                    else {}
                ),
            },
        }
        if model_request.thinking is not None:
            payload["think"] = model_request.thinking

        value = self._json_request("POST", "/api/chat", payload)
        message = value.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise RuntimeError("Ollama response is missing message.content")
        usage = {"model_calls": 1}
        for source, meter in [
            ("prompt_eval_count", "input_tokens"),
            ("eval_count", "output_tokens"),
        ]:
            if type(value.get(source)) is int and value[source] >= 0:
                usage[meter] = value[source]
        total_duration = value.get("total_duration")
        if type(total_duration) is int and total_duration >= 0:
            usage["model_duration_ns"] = total_duration
        used = value.get("prompt_eval_count")
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
        # Ollama 的 length 表示输出预算耗尽，即使正文是合法 JSON 也不能证明自然语言完整。
        # 模型已返回结果与计量，属于已知失败；不能内部盲目重发同一 Ticket。
        done_reason = value.get("done_reason")
        if done_reason == "length":
            raise OutputTruncated(
                "Ollama output truncated: generation reached max_output_tokens; "
                "increase the output limit or reduce prompt/response complexity",
                usage=usage,
                raw=value,
            )
        if value.get("done") is False:
            raise OutputTruncated(
                "Ollama returned an incomplete generation (done=false)",
                usage=usage,
                raw=value,
            )
        return ModelResult(
            text=message["content"],
            usage=usage,
            raw=value,
            response_id=None,
        )
