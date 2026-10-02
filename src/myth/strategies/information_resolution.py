"""Rule-based Information Resolution controller.

This chooses how much of the *same fixed source* to project into context.
It does not estimate Information Gain and does not change source identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ..domains.information import InformationResolution, IntentRoute


_DEEP_CUE = re.compile(
    r"(?:原文|全文|详细|具体|逐字|证据|出处|展开|"
    r"full\s*text|detail|exact\s+wording|evidence|source\s+text)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResolutionPlan:
    resolution: InformationResolution
    max_sources: int
    max_chars_per_source: int
    reason: str

    def serializable(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "max_sources": self.max_sources,
            "max_chars_per_source": self.max_chars_per_source,
            "reason": self.reason,
        }


class RuleResolutionController:
    strategy_id = "information_resolution"

    def choose(
        self,
        text: str,
        *,
        route: IntentRoute,
        sources: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        attached_document_ids: list[str] | tuple[str, ...] = (),
    ) -> ResolutionPlan:
        if not sources:
            return ResolutionPlan(
                InformationResolution.L0,
                0,
                0,
                "no admitted local source is available",
            )
        if attached_document_ids:
            return ResolutionPlan(
                InformationResolution.L2,
                2,
                6000,
                "explicitly attached documents deserve detailed source projection",
            )
        if _DEEP_CUE.search(str(text or "")):
            return ResolutionPlan(
                InformationResolution.L2,
                2,
                6000,
                "user requested detailed/source-level evidence",
            )
        if route is IntentRoute.LOCAL_RETRIEVAL:
            return ResolutionPlan(
                InformationResolution.L1,
                5,
                1800,
                "local-retrieval route needs navigable source chunks before deeper expansion",
            )
        return ResolutionPlan(
            InformationResolution.L0,
            5,
            500,
            "general Agent route receives lightweight source previews by default",
        )
