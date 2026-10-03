"""本机 Ollama HTTP 适配器。
把统一请求转换为 /api/chat，窗口与本地投影对齐；仅能证明未接收的连接错误可重试，派发后不明结果交回 Runtime 核对。"""

from __future__ import annotations

import json
import socket
from urllib import error, request

from ..models import ContextTruncated, ModelRequest, ModelResult, ProviderStatus


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
        # timeout：一次网络/操作等待的上限，单位秒；超时不能证明远端未执行。
        self.timeout = timeout
        # keep_alive：Ollama 模型驻留选项；控制加载生命周期，不代表业务状态。
        self.keep_alive = keep_alive

    # 执行有界 HTTP JSON 请求；只重试可证明未被接收的拒连/DNS，超时和派发后异常保留不明结果。
    def _json_request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
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
        raw = None
        for attempt in range(2):
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = response.read()
                break
            except error.URLError as exc:
                # 仅连接拒绝/DNS 等能证明请求未被接受的情况可本地重试；超时等派发后不确定保持单次调用，交 Runtime 记为 UNKNOWN。
                reason = getattr(exc, "reason", None)
                pre_dispatch = isinstance(
                    reason, (ConnectionRefusedError, socket.gaierror)
                )
                if attempt == 0 and pre_dispatch:
                    continue
                raise RuntimeError(f"Ollama request failed: {exc}") from exc
        if raw is None:
            raise RuntimeError("Ollama request produced no response bytes")
        value = json.loads(raw.decode("utf-8"))
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
        except Exception as exc:
            return ProviderStatus(
                self.provider_id, False, auth_type="none", details={"error": str(exc)}
            )

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
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
        return ModelResult(
            text=message["content"],
            usage=usage,
            raw=value,
            response_id=None,
        )
