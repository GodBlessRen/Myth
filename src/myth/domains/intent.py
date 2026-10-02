"""Intent Pick contracts.

Intent Pick asks the cheapest useful question first: which processing path is
appropriate?  It does not grant execution authority and is not tied to an LLM.
"""

from __future__ import annotations

from typing import Any, Protocol

from .information import IntentPick


class IntentPicker(Protocol):
    def pick(self, value: str, context: dict[str, Any]) -> IntentPick: ...


__all__ = ["IntentPick", "IntentPicker"]
