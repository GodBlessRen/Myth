"""Evaluation gates: quality/safety gates precede optimization metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalReport:
    suite_id: str
    pass_count: int
    fail_count: int
    inconclusive_count: int
    safety_regressions: int
    measured_cost: int | None = None

    @property
    def total(self) -> int:
        return self.pass_count + self.fail_count + self.inconclusive_count


def release_gate(report: EvalReport, *, min_pass_rate: float = 0.95) -> tuple[bool, str]:
    if report.total <= 0:
        return False, "empty evaluation suite"
    if report.safety_regressions:
        return False, "safety/runtime invariant regression"
    rate = report.pass_count / report.total
    if rate < min_pass_rate:
        return False, f"pass rate {rate:.3f} below {min_pass_rate:.3f}"
    if report.inconclusive_count:
        return False, "inconclusive cases remain"
    return True, "quality gate passed"
