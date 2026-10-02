"""Provider boundary for model I/O.

A provider performs network/process I/O but never mutates Myth Run state. The
Runtime owns admission, Tickets, durable request/response artifacts and usage
settlement around this boundary.
"""

from __future__ import annotations

from typing import Protocol

from ..models import ModelRequest, ModelResult, ProviderStatus


class ModelProvider(Protocol):
    provider_id: str

    def check(self) -> ProviderStatus:
        ...

    def invoke(self, request: ModelRequest) -> ModelResult:
        ...
