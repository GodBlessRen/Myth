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
class EvalSuite:
    suite_id: str
    version: int
    principle: str
    cases: tuple[EvalCase, ...]

    def __post_init__(self) -> None:
        if not self.suite_id.strip() or self.version < 1:
            raise ValueError("eval suite id/version are required")
        ids=[case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("eval suite contains duplicate case ids")


@dataclass(frozen=True)
class EvalObservation:
    case_id: str
    verdict: EvalVerdict
    reason: str
    metrics: dict[str, float | int] | None = None
    evidence_refs: tuple[str, ...] = ()
    safety_regression: bool = False
    policy_id: str | None = None
    comparison_key: str | None = None


@dataclass(frozen=True)
class PairedEvalComparison:
    case_id: str
    comparison_key: str
    baseline_policy_id: str
    candidate_policy_id: str
    baseline_verdict: EvalVerdict
    candidate_verdict: EvalVerdict
    observed_quality_gain: float | None
    cost_delta: dict[str, float]
    evidence_refs: tuple[str, ...] = ()

    @property
    def calibrated(self) -> bool:
        return self.observed_quality_gain is not None


def _verdict_quality(verdict: EvalVerdict) -> float | None:
    if verdict is EvalVerdict.PASS:
        return 1.0
    if verdict is EvalVerdict.FAIL:
        return 0.0
    return None


def compare_observations(
    baseline: EvalObservation,
    candidate: EvalObservation,
) -> PairedEvalComparison:
    if baseline.case_id != candidate.case_id:
        raise ValueError("paired evaluation requires the same case_id")
    baseline_key=baseline.comparison_key or baseline.case_id
    candidate_key=candidate.comparison_key or candidate.case_id
    if baseline_key != candidate_key:
        raise ValueError("paired evaluation requires the same comparison_key")
    if not baseline.policy_id or not candidate.policy_id:
        raise ValueError("paired evaluation requires explicit policy_id values")

    baseline_quality=_verdict_quality(baseline.verdict)
    candidate_quality=_verdict_quality(candidate.verdict)
    quality_gain=(
        None
        if baseline_quality is None or candidate_quality is None
        else candidate_quality-baseline_quality
    )
    baseline_metrics=baseline.metrics or {}
    candidate_metrics=candidate.metrics or {}
    keys=set(baseline_metrics) | set(candidate_metrics)
    cost_delta={}
    for key in sorted(keys):
        before=baseline_metrics.get(key)
        after=candidate_metrics.get(key)
        if isinstance(before,(int,float)) and isinstance(after,(int,float)):
            cost_delta[key]=float(after)-float(before)

    return PairedEvalComparison(
        case_id=baseline.case_id,
        comparison_key=baseline_key,
        baseline_policy_id=baseline.policy_id,
        candidate_policy_id=candidate.policy_id,
        baseline_verdict=baseline.verdict,
        candidate_verdict=candidate.verdict,
        observed_quality_gain=quality_gain,
        cost_delta=cost_delta,
        evidence_refs=tuple(dict.fromkeys((*baseline.evidence_refs,*candidate.evidence_refs))),
    )


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



def load_eval_suite(path: str | Path) -> EvalSuite:
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict) or not isinstance(value.get("cases"),list):
        raise ValueError("eval suite must contain a cases array")
    cases=[]
    for raw in value["cases"]:
        if not isinstance(raw,dict):
            raise ValueError("eval case must be an object")
        cases.append(EvalCase(
            case_id=str(raw.get("case_id") or ""),
            category=str(raw.get("category") or ""),
            input=dict(raw.get("input") or {}),
            expected=dict(raw.get("expected") or {}),
            safety_critical=bool(raw.get("safety_critical",False)),
        ))
    return EvalSuite(
        suite_id=str(value.get("suite_id") or ""),
        version=int(value.get("version") or 0),
        principle=str(value.get("principle") or ""),
        cases=tuple(cases),
    )


def load_eval_cases(path: str | Path) -> tuple[EvalCase, ...]:
    return load_eval_suite(path).cases


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
