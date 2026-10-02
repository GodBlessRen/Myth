"""Conservative deterministic Intent Pick baseline.

Only inputs that are entirely a bounded arithmetic expression (optionally
prefixed by a small explicit calculate verb) take the deterministic fast path.
Everything else falls back to the Agent Loop.
"""

from __future__ import annotations

import re
from typing import Any

from ..domains.information import IntentPick, IntentRoute


_PREFIX = re.compile(r"^\s*(?:计算|算一下|算|calculate|calc)\s*[:：]?\s*", re.IGNORECASE)
_ALLOWED = re.compile(r"^[0-9eE+\-*/%().\s]+$")


class RuleIntentPicker:
    strategy_id = "intent_pick"

    def pick(self, value: str, context: dict[str, Any]) -> IntentPick:
        text = str(value or "")
        candidate = _PREFIX.sub("", text, count=1).strip()
        if (
            candidate
            and len(candidate) <= 200
            and _ALLOWED.fullmatch(candidate)
            and any(ch.isdigit() for ch in candidate)
            and any(op in candidate for op in ("+", "-", "*", "/", "%"))
        ):
            return IntentPick(
                route=IntentRoute.DETERMINISTIC,
                objective="evaluate bounded arithmetic locally",
                confidence=1.0,
                reason="input is entirely within the admitted arithmetic grammar",
                metadata={"kind": "bounded_arithmetic", "expression": candidate},
            )
        return IntentPick(
            route=IntentRoute.AGENT,
            objective="continue through the general conversation agent",
            reason="no conservative deterministic route matched",
        )
