"""Conservative pre-reasoning Intent Pick cascade.

The picker only promotes routes with explicit/local evidence:
1. bounded arithmetic -> deterministic;
2. explicit/strong local knowledge evidence -> local_retrieval;
3. everything else -> Agent Loop.

A route pick never grants execution authority.
"""

from __future__ import annotations

import re
from typing import Any

from ..domains.information import IntentPick, IntentRoute


_PREFIX = re.compile(r"^\s*(?:计算|算一下|算|calculate|calc)\s*[:：]?\s*", re.IGNORECASE)
_ALLOWED = re.compile(r"^[0-9eE+\-*/%().\s]+$")
_KNOWLEDGE_CUE = re.compile(
    r"(?:根据|查(?:一下)?|搜索|检索|资料|知识库|文档|附件|原文|出处|证据|"
    r"according\s+to|knowledge\s*base|docs?|document|attachment|source|evidence)",
    re.IGNORECASE,
)


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

        sources = tuple(context.get("sources") or ())
        attached = tuple(context.get("attached_document_ids") or ())
        top_score = max(
            (float(item.get("score") or 0.0) for item in sources if isinstance(item, dict)),
            default=0.0,
        )
        explicit = bool(_KNOWLEDGE_CUE.search(text)) or bool(attached)
        if sources and (explicit or top_score >= 1.25):
            return IntentPick(
                route=IntentRoute.LOCAL_RETRIEVAL,
                objective="ground the response in admitted local knowledge before general reasoning",
                confidence=1.0 if explicit else min(0.99, top_score / 2.0),
                reason=(
                    "user explicitly requested local/source evidence"
                    if explicit
                    else "local lexical retrieval produced a strong source match"
                ),
                metadata={
                    "kind": "local_knowledge",
                    "source_count": len(sources),
                    "top_score": round(top_score, 3),
                    "explicit_source_request": explicit,
                },
            )

        return IntentPick(
            route=IntentRoute.AGENT,
            objective="continue through the general conversation agent",
            reason="no conservative deterministic or local-retrieval route matched",
        )
