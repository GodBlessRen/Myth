"""DeepSeek Responses API 传输适配器。
沿用统一 ModelProvider / durable receipt 合同，只在供应商边界映射角色、thinking 与公开模型目录；
API key 仅在调用时从环境变量读取，不进入 SQLite、事件、Web JSON 或模型结果。
"""

from __future__ import annotations

import os

from ..models import ModelRequest, ProviderStatus
from .openai import OpenAIResponsesProvider


# DeepSeek 官方 Responses API 根地址；固定 HTTPS 端点避免用户设置把凭据发送到任意主机。
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# 当前 Responses API 文档公开模型目录；目录是产品提示，不代表远端某次请求一定成功。
DEEPSEEK_MODELS = ("deepseek-flash", "deepseek-v4-pro")


# DeepSeek API Key 适配器；复用 Responses 传输/恢复语义，不复制 Agent Loop 或业务状态。
class DeepSeekApiKeyProvider(OpenAIResponsesProvider):
    # provider_id：供应商合同身份；Run/Turn 固定后恢复时必须仍使用同一身份。
    provider_id = "deepseek"

    # 只保存非秘钥端点/超时配置；key 每次从环境读取，支持进程级轮换且不产生持久副本。
    def __init__(self, env_var: str = "DEEPSEEK_API_KEY", timeout: float = 180.0) -> None:
        # token：调用边界即时读取环境变量；缺失属于派发前已知失败，不进入 UNKNOWN。
        def token() -> str:
            value = os.environ.get(env_var, "").strip()
            if not value:
                raise RuntimeError(f"{env_var} is not set")
            return value

        # status_check：只证明凭据存在及当前客户端支持哪些官方模型；不发业务推理请求。
        def status_check() -> ProviderStatus:
            try:
                token()
            except Exception:
                return ProviderStatus(
                    self.provider_id,
                    False,
                    auth_type="api_key",
                    details={
                        "error": f"{env_var} is not set",
                        "models": list(DEEPSEEK_MODELS),
                    },
                )
            return ProviderStatus(
                self.provider_id,
                True,
                auth_type="api_key",
                details={
                    "models": list(DEEPSEEK_MODELS),
                    "endpoint": DEEPSEEK_BASE_URL,
                },
            )

        super().__init__(
            provider_id=self.provider_id,
            token_supplier=token,
            base_url=DEEPSEEK_BASE_URL,
            timeout=timeout,
            chatgpt_plan=False,
            auth_type="api_key",
            status_check=status_check,
            provider_name="DeepSeek",
        )

    # DeepSeek 将 developer 当 user，因此必须保留 system 角色，避免系统约束静默降级。
    def _message_role(self, role: str) -> str:
        return role

    # 将 Myth 的统一 thinking 开关/等级映射到 DeepSeek reasoning.effort；None 保留供应商默认。
    def _reasoning_options(self, model_request: ModelRequest) -> dict | None:
        thinking = model_request.thinking
        if thinking is None:
            return None
        if thinking is True:
            return {"effort": "high"}
        if thinking is False:
            return {"effort": "none"}
        value = str(thinking).strip().lower()
        if value in {"", "default"}:
            return None
        aliases = {
            "off": "none",
            "false": "none",
            "none": "none",
            "minimal": "low",
            "low": "low",
            "medium": "high",
            "high": "high",
            "xhigh": "high",
            "max": "max",
        }
        effort = aliases.get(value)
        if effort is None:
            raise ValueError(f"unsupported DeepSeek thinking level: {thinking}")
        return {"effort": effort}

    # DeepSeek Responses 支持 temperature；thinking 模式下远端可能忽略它，但仍保持请求配置可观测一致。
    def _extra_payload(self, model_request: ModelRequest) -> dict:
        return {"temperature": float(model_request.temperature)}
