"""Controlled policy evolution skeleton; candidates never mutate the live Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .evaluation import EvalReport, release_gate


class PromotionDecision(StrEnum):
    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


@dataclass(frozen=True)
class PolicyCandidate:
    candidate_id: str
    baseline_version: str
    candidate_version: str
    changes: tuple[str, ...]


def decide_promotion(candidate: PolicyCandidate, report: EvalReport) -> tuple[PromotionDecision, str]:
    passed, reason = release_gate(report)
    if not passed:
        return PromotionDecision.HOLD, reason
    if not candidate.changes:
        return PromotionDecision.REJECT, "candidate contains no declared changes"
    return PromotionDecision.PROMOTE, "eligible for explicit release; not auto-published"
