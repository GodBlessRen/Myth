"""统一供应商适配器导出。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from __future__ import annotations

from typing import Callable

from .base import ModelProvider
from .deepseek import DeepSeekApiKeyProvider
from .ollama import OllamaProvider
from .openai import ChatGPTPlanProvider, OpenAIApiKeyProvider
from .scripted import ScriptedPatchProvider
from ..auth.provider_keys import ProviderApiKeyVault


# 按明确 provider_id 在装配边界创建具体供应商；配置不携带其他应用认证文件或扩大工具权限。
def create_provider(
    name: str,
    *,
    ollama_base_url: str | None = None,
    runtime_root: str | None = None,
    token_supplier: Callable[[], str] | None = None,
) -> ModelProvider:
    if name == "scripted":
        return ScriptedPatchProvider()
    if name == "ollama":
        return OllamaProvider(base_url=ollama_base_url or "http://127.0.0.1:11434")
    if name == "chatgpt":
        if runtime_root is None:
            raise ValueError("chatgpt provider requires runtime_root")
        return ChatGPTPlanProvider(runtime_root)
    if name in {"openai", "deepseek"}:
        if runtime_root is None:
            raise ValueError(f"{name} provider requires runtime_root")
        vault = ProviderApiKeyVault()
        token = token_supplier or (lambda: vault.resolve(name)[0])
        return (
            OpenAIApiKeyProvider(token_supplier=token)
            if name == "openai"
            else DeepSeekApiKeyProvider(token_supplier=token)
        )
    raise ValueError(f"unknown provider: {name}")


# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = [
    "ModelProvider",
    "OllamaProvider",
    "DeepSeekApiKeyProvider",
    "OpenAIApiKeyProvider",
    "ChatGPTPlanProvider",
    "create_provider",
]
