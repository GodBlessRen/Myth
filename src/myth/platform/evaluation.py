"""Evaluation contracts: quality/safety evidence precedes optimization claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Iterable


class EvalVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    input: dict[str, Any]
    expected: dict[str, Any]
    safety_critical: bool = False

    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.category.strip():
            raise ValueError("eval case id/category are required")


@dataclass(frozen=True)
class EvalObservation:
    case_id: str
    verdict: EvalVerdict
    reason: str
    metrics: dict[str, float | int] | None = None
    evidence_refs: tuple[str, ...] = ()
    safety_regression: bool = False


@dataclass(frozen=True)
class EvalReport:
    suite_id: str
    pass_count: int
    fail_count: int
    inconclusive_count: int
    safety_regressions: int
    measured_cost: int | None = None
    unsupported_count: int = 0

    @property
    def total(self) -> int:
        return (
            self.pass_count
            + self.fail_count
            + self.inconclusive_count
            + self.unsupported_count
        )

    @property
    def measured_total(self) -> int:
        return self.pass_count + self.fail_count + self.inconclusive_count



def load_eval_cases(path: str | Path) -> tuple[EvalCase, ...]:
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict) or not isinstance(value.get("cases"),list):
        raise ValueError("eval suite must contain a cases array")
    cases=[]
    seen=set()
    for raw in value["cases"]:
        if not isinstance(raw,dict):
            raise ValueError("eval case must be an object")
        case=EvalCase(
            case_id=str(raw.get("case_id") or ""),
            category=str(raw.get("category") or ""),
            input=dict(raw.get("input") or {}),
            expected=dict(raw.get("expected") or {}),
            safety_critical=bool(raw.get("safety_critical",False)),
        )
        if case.case_id in seen:
            raise ValueError(f"duplicate eval case: {case.case_id}")
        seen.add(case.case_id);cases.append(case)
    return tuple(cases)


def summarize_observations(
    suite_id: str,
    observations: Iterable[EvalObservation],
) -> EvalReport:
    values=tuple(observations)
    return EvalReport(
        suite_id=suite_id,
        pass_count=sum(item.verdict is EvalVerdict.PASS for item in values),
        fail_count=sum(item.verdict is EvalVerdict.FAIL for item in values),
        inconclusive_count=sum(item.verdict is EvalVerdict.INCONCLUSIVE for item in values),
        unsupported_count=sum(item.verdict is EvalVerdict.UNSUPPORTED for item in values),
        safety_regressions=sum(bool(item.safety_regression) for item in values),
        measured_cost=sum(
            int((item.metrics or {}).get("cost",0))
            for item in values
            if (item.metrics or {}).get("cost") is not None
        ),
    )


def release_gate(report: EvalReport, *, min_pass_rate: float = 0.95) -> tuple[bool, str]:
    if report.total <= 0:
        return False, "empty evaluation suite"
    if report.safety_regressions:
        return False, "safety/runtime invariant regression"
    if report.unsupported_count:
        return False, "unsupported cases remain"
    if report.measured_total <= 0:
        return False, "no measured evaluation cases"
    rate = report.pass_count / report.measured_total
    if rate < min_pass_rate:
        return False, f"pass rate {rate:.3f} below {min_pass_rate:.3f}"
    if report.inconclusive_count:
        return False, "inconclusive cases remain"
    return True, "quality gate passed"
