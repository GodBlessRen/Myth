"""Conservative pre-reasoning Intent Pick cascade.

The picker promotes only routes with evidence strong enough to avoid common
shape collisions (dates, versions, percentages, generic "docs/source" prose).
A route pick never grants execution authority.
"""

from __future__ import annotations

import re
from typing import Any

from ..domains.information import IntentPick, IntentRoute


_PREFIX = re.compile(r"^\s*(?:计算|算一下|算|calculate|calc)\s*[:：]?\s*", re.IGNORECASE)
_ALLOWED = re.compile(r"^[0-9eE+\-*/%().\s]+$")
_BIN = re.compile(r"[\d)]\s*(?:\*\*|[+\-*/%])\s*[\d(.+\-]")

_STRONG_KNOWLEDGE_CUE = re.compile(
    r"(?:知识库|附件|原文|出处|"
    r"根据.{0,16}(?:资料|文档|附件|知识库|原文)|"
    r"according\s+to.{0,16}(?:docs?|document|attachment|source)|"
    r"knowledge\s*base|attached\s+(?:file|document)|attachment)",
    re.IGNORECASE,
)
_WEAK_KNOWLEDGE_CUE = re.compile(
    r"(?:资料|文档|docs?|document|source|evidence|查(?:一下)?|搜索|检索)",
    re.IGNORECASE,
)

# Existing lexical baseline threshold. foundation-v4 adversarial cases freeze the
# behavior; changing it later requires eval evidence rather than intuition.
_WEAK_CUE_SCORE_THRESHOLD = 1.25


def _arithmetic_candidate(text: str) -> tuple[bool, str]:
    prefixed = bool(_PREFIX.match(text))
    candidate = _PREFIX.sub("", text, count=1).strip()
    if not (
        candidate
        and len(candidate) <= 200
        and _ALLOWED.fullmatch(candidate)
        and _BIN.search(candidate)
    ):
        return False, candidate

    # Without an explicit arithmetic prefix, "/" "-" "%" are too ambiguous:
    # dates, versions, fractions, phone-like strings and percentages all share
    # those characters. "+" / "*" / parentheses are much stronger signals.
    if not prefixed and not re.search(r"[+*(]", candidate):
        return False, candidate
    if candidate.rstrip().endswith("%"):
        return False, candidate
    return True, candidate


class RuleIntentPicker:
    strategy_id = "intent_pick"

    def pick(self, value: str, context: dict[str, Any]) -> IntentPick:
        text = str(value or "")
        arithmetic, candidate = _arithmetic_candidate(text)
        if arithmetic:
            return IntentPick(
                route=IntentRoute.DETERMINISTIC,
                objective="evaluate bounded arithmetic locally",
                confidence=1.0,
                reason="input satisfies the conservative arithmetic grammar",
                metadata={"kind": "bounded_arithmetic", "expression": candidate},
            )

        sources = tuple(context.get("sources") or ())
        attached = tuple(context.get("attached_document_ids") or ())
        top_score = max(
            (float(item.get("score") or 0.0) for item in sources if isinstance(item, dict)),
            default=0.0,
        )
        strong = bool(attached) or bool(_STRONG_KNOWLEDGE_CUE.search(text))
        weak = bool(_WEAK_KNOWLEDGE_CUE.search(text))

        local_evidence = bool(sources) and (
            strong
            or top_score >= _WEAK_CUE_SCORE_THRESHOLD
            or (weak and top_score >= _WEAK_CUE_SCORE_THRESHOLD)
        )
        if local_evidence:
            return IntentPick(
                route=IntentRoute.LOCAL_RETRIEVAL,
                objective="ground the response in admitted local knowledge before general reasoning",
                confidence=(
                    1.0
                    if strong
                    else min(0.99, top_score / 2.0)
                ),
                reason=(
                    "user explicitly requested admitted local/source evidence"
                    if strong
                    else "local lexical retrieval produced a strong source match"
                ),
                metadata={
                    "kind": "local_knowledge",
                    "source_count": len(sources),
                    "top_score": round(top_score, 3),
                    "strong_source_request": strong,
                    "weak_source_cue": weak,
                    "score_threshold": _WEAK_CUE_SCORE_THRESHOLD,
                },
            )

        return IntentPick(
            route=IntentRoute.AGENT,
            objective="continue through the general conversation agent",
            reason="no conservative deterministic or local-retrieval route matched",
        )
