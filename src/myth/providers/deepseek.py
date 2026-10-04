"""DeepSeek Responses API 传输适配器。
沿用统一 ModelProvider / durable receipt 合同，只在供应商边界映射角色、thinking 与公开模型目录；
API key 仅在调用时从环境变量读取，不进入 SQLite、事件、Web JSON 或模型结果。
"""

from __future__ import annotations

import json
from urllib import request

from ..auth.transport import open_credential_request, read_bounded
from ..models import ModelRequest, ProviderStatus
from .capabilities import model_capability, reasoning_capability
from .openai import OpenAIResponsesProvider, TokenSupplier


# DeepSeek 官方 Responses API 根地址；固定 HTTPS 端点避免用户设置把凭据发送到任意主机。
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# DeepSeek API Key 适配器；复用 Responses 传输/恢复语义，不复制 Agent Loop 或业务状态。
class DeepSeekApiKeyProvider(OpenAIResponsesProvider):
    # provider_id：供应商合同身份；Run/Turn 固定后恢复时必须仍使用同一身份。
    provider_id = "deepseek"

    # 只保存非秘钥端点/超时配置；key 每次从环境读取，支持进程级轮换且不产生持久副本。
    def __init__(
        self,
        env_var: str = "DEEPSEEK_API_KEY",
        timeout: float = 180.0,
        token_supplier: TokenSupplier | None = None,
    ) -> None:
        # token_supplier 由 Credential Hub 注入；环境变量仅保留兼容旧部署，不再要求用户先开 PowerShell。
        def env_token() -> str:
            import os
            value = os.environ.get(env_var, "").strip()
            if not value:
                raise RuntimeError(f"{env_var} is not set")
            return value

        token = token_supplier or env_token

        # status_check：读取 DeepSeek 官方 /models 公开能力目录；失败不回退到写死模型表，避免过期能力误导 UI。
        def status_check() -> ProviderStatus:
            try:
                access_token = token()
            except Exception:
                return ProviderStatus(
                    self.provider_id,
                    False,
                    auth_type="api_key",
                    details={"error": f"{env_var} is not set"},
                )
            try:
                req = request.Request(
                    f"{DEEPSEEK_BASE_URL}/models",
                    method="GET",
                    headers={
                        "authorization": f"Bearer {access_token}",
                        "accept": "application/json",
                    },
                )
                with open_credential_request(req, timeout=min(timeout, 30.0)) as response:
                    value = json.loads(read_bounded(response).decode("utf-8"))
                rows = value.get("data") if isinstance(value, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("invalid model catalog")
                profiles = {}
                for item in rows:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                        continue
                    effort = item.get("effort") if isinstance(item.get("effort"), dict) else {}
                    reasoning = None
                    levels = effort.get("supported_levels")
                    if isinstance(levels, list):
                        reasoning = reasoning_capability(
                            kind="effort",
                            levels=[level for level in levels if isinstance(level, str)],
                            default=effort.get("default_level"),
                            off="none",
                            source="remote",
                        )
                    # known 字段进入跨 Provider capability；其余 DeepSeek 目录元数据原样留在折叠层，避免未来字段被静默丢弃。
                    known = {
                        "id", "name", "context_window", "max_output_tokens",
                        "input_modalities", "output_modalities", "effort",
                    }
                    provider_metadata = {
                        str(key): value
                        for key, value in item.items()
                        if key not in known
                    }
                    profile = model_capability(
                        item["id"],
                        display_name=item.get("name"),
                        context_window=item.get("context_window"),
                        max_output_tokens=item.get("max_output_tokens"),
                        input_modalities=item.get("input_modalities") or (),
                        output_modalities=item.get("output_modalities") or (),
                        reasoning=reasoning,
                        provider_metadata=provider_metadata,
                        source="remote",
                    )
                    profiles[item["id"]] = profile
                models = list(profiles)
                return ProviderStatus(
                    self.provider_id,
                    bool(models),
                    auth_type="api_key",
                    details={
                        "models": models,
                        "model_capabilities": profiles,
                        "endpoint": DEEPSEEK_BASE_URL,
                        "capability_source": "remote",
                    },
                )
            except Exception:
                return ProviderStatus(
                    self.provider_id,
                    False,
                    auth_type="api_key",
                    details={"error": "DeepSeek model capability catalog is unavailable"},
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

    # 将用户选择直接投影到 DeepSeek 原生 effort；字符串不做跨厂商档位映射，旧 bool 仅保留开关兼容。
    def _reasoning_options(self, model_request: ModelRequest) -> dict | None:
        thinking = model_request.thinking
        if thinking is None:
            return None
        if thinking is True:
            return {}
        if thinking is False:
            return {"effort": "none"}
        value = str(thinking).strip().lower()
        if value in {"", "default"}:
            return None
        return {"effort": value}

    # DeepSeek Responses 支持 temperature；thinking 模式下远端可能忽略它，但仍保持请求配置可观测一致。
    def _extra_payload(self, model_request: ModelRequest) -> dict:
        return {"temperature": float(model_request.temperature)}
