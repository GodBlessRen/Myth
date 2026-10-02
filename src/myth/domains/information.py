"""Information contracts for progressive disclosure and marginal value.

The contracts intentionally do not prescribe whether estimates come from rules,
Jev, a small model, embeddings, an LLM, or offline statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class InformationResolution(StrEnum):
    """Resolution of the same underlying information, not answer confidence."""

    L0 = "L0"  # abstract / tiny retrieval representation
    L1 = "L1"  # overview / navigational representation
    L2 = "L2"  # detailed evidence / source-of-truth representation


@dataclass(frozen=True)
class InformationView:
    source_ref: str
    resolution: InformationResolution
    content: str
    provenance_ref: str | None = None
    token_estimate: int | None = None


@dataclass(frozen=True)
class InformationDelta:
    """What changed between two information states."""

    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    conflicted: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return any((self.added, self.updated, self.removed, self.conflicted))


@dataclass(frozen=True)
class InformationGain:
    """Estimated marginal task value of acquiring/expanding information.

    This is not claimed to be Shannon mutual information.  A concrete estimator
    must declare its own semantics before the numeric score is trusted.
    """

    source_ref: str
    from_resolution: InformationResolution | None
    to_resolution: InformationResolution
    estimated_gain: float | None = None
    estimated_cost: float | None = None
    estimator: str | None = None

    @property
    def gain_per_cost(self) -> float | None:
        if self.estimated_gain is None or self.estimated_cost in (None, 0):
            return None
        return self.estimated_gain / self.estimated_cost


class IntentRoute(StrEnum):
    """Processing path selected before expensive reasoning is assumed."""

    DIRECT = "direct"
    LOCAL_RETRIEVAL = "local_retrieval"
    DETERMINISTIC = "deterministic"
    AGENT = "agent"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class IntentPick:
    """A route pick, not a hard semantic class for the user."""

    route: IntentRoute
    objective: str | None = None
    confidence: float | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None
