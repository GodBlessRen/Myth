"""统一供应商适配器导出。
包导出本身不启动业务工作；具体状态归属、I/O 和恢复合同见被导出模块。"""

from __future__ import annotations

from .base import ModelProvider
from .ollama import OllamaProvider
from .openai import ChatGPTPlanProvider, OpenAIApiKeyProvider
from .scripted import ScriptedPatchProvider


# 按明确 provider_id 在装配边界创建具体供应商；配置不携带其他应用认证文件或扩大工具权限。
def create_provider(
    name: str, *, ollama_base_url: str | None = None, runtime_root: str | None = None
) -> ModelProvider:
    if name == "scripted":
        return ScriptedPatchProvider()
    if name == "ollama":
        return OllamaProvider(base_url=ollama_base_url or "http://127.0.0.1:11434")
    if name == "chatgpt":
        if runtime_root is None:
            raise ValueError("chatgpt provider requires runtime_root")
        return ChatGPTPlanProvider(runtime_root)
    if name == "pi-openai":
        raise ValueError(
            "legacy pi-openai authentication was removed; sign in with Myth OAuth and use provider=chatgpt"
        )
    if name == "openai":
        return OpenAIApiKeyProvider()
    raise ValueError(f"unknown provider: {name}")


# __all__：公开导出名单；兼容别名只有在确认外部迁移完成后才删除。
__all__ = [
    "ModelProvider",
    "OllamaProvider",
    "OpenAIApiKeyProvider",
    "ChatGPTPlanProvider",
    "create_provider",
]
