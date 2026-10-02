"""Built-in model providers."""

from __future__ import annotations

from .base import ModelProvider
from .ollama import OllamaProvider
from .openai import ChatGPTPlanProvider, OpenAIApiKeyProvider
from .scripted import ScriptedPatchProvider


def create_provider(name: str, *, ollama_base_url: str | None = None, runtime_root: str | None = None) -> ModelProvider:
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


__all__ = [
    "ModelProvider",
    "OllamaProvider",
    "OpenAIApiKeyProvider",
    "ChatGPTPlanProvider",
    "create_provider",
]
