"""Built-in model providers."""

from __future__ import annotations

from .base import ModelProvider
from .ollama import OllamaProvider
from .openai import OpenAIApiKeyProvider, PiOpenAIProvider


def create_provider(name: str, *, ollama_base_url: str | None = None, pi_command: str = "pi") -> ModelProvider:
    if name == "ollama":
        return OllamaProvider(base_url=ollama_base_url or "http://127.0.0.1:11434")
    if name == "pi-openai":
        return PiOpenAIProvider(pi_command=pi_command)
    if name == "openai":
        return OpenAIApiKeyProvider()
    raise ValueError(f"unknown provider: {name}")


__all__ = [
    "ModelProvider",
    "OllamaProvider",
    "OpenAIApiKeyProvider",
    "PiOpenAIProvider",
    "create_provider",
]
