"""Aggregate paired evaluation evidence without hiding case-level facts."""

from __future__ import annotations

from dataclasses import dataclass

from .cost_model import CostModel
from .evaluation import PairedEvalComparison


@dataclass(frozen=True)
class GainCalibrationMatrix:
    total_pairs: int
    calibrated_pairs: int
    positive_pairs: int
    zero_pairs: int
    negative_pairs: int
    uncalibrated_pairs: int
    total_quality_gain: float
    mean_quality_gain: float | None
    total_weighted_cost: float | None
    gain_per_cost: float | None
    regression_cases: tuple[str,...]
    uncalibrated_cases: tuple[str,...]
    cost_model_id: str | None

    @property
    def coverage(self) -> float:
        return 0.0 if self.total_pairs==0 else self.calibrated_pairs/self.total_pairs

    def serializable(self) -> dict:
        return {
            "total_pairs":self.total_pairs,
            "calibrated_pairs":self.calibrated_pairs,
            "positive_pairs":self.positive_pairs,
            "zero_pairs":self.zero_pairs,
            "negative_pairs":self.negative_pairs,
            "uncalibrated_pairs":self.uncalibrated_pairs,
            "coverage":self.coverage,
            "total_quality_gain":self.total_quality_gain,
            "mean_quality_gain":self.mean_quality_gain,
            "total_weighted_cost":self.total_weighted_cost,
            "gain_per_cost":self.gain_per_cost,
            "regression_cases":list(self.regression_cases),
            "uncalibrated_cases":list(self.uncalibrated_cases),
            "cost_model_id":self.cost_model_id,
        }

    def promotion_gate(self, *, min_pairs: int = 1, require_full_coverage: bool = True) -> tuple[bool,str]:
        if self.calibrated_pairs < min_pairs:
            return False,f"only {self.calibrated_pairs} calibrated pairs; require {min_pairs}"
        if require_full_coverage and self.uncalibrated_pairs:
            return False,"uncalibrated paired cases remain"
        if self.negative_pairs:
            return False,"candidate regresses one or more fixed cases"
        return True,"paired calibration gate passed"


def build_calibration_matrix(
    comparisons: list[PairedEvalComparison] | tuple[PairedEvalComparison,...],
    cost_model: CostModel | None = None,
) -> GainCalibrationMatrix:
    values=tuple(comparisons)
    calibrated=[item for item in values if item.observed_quality_gain is not None]
    gains=[float(item.observed_quality_gain) for item in calibrated]
    regressions=tuple(item.case_id for item in calibrated if float(item.observed_quality_gain)<0)
    unknown=tuple(item.case_id for item in values if item.observed_quality_gain is None)
    weighted=None
    if cost_model is not None:
        weighted=sum(cost_model.weighted_cost(item.cost_delta) for item in calibrated)
    total_gain=sum(gains)
    return GainCalibrationMatrix(
        total_pairs=len(values),
        calibrated_pairs=len(calibrated),
        positive_pairs=sum(value>0 for value in gains),
        zero_pairs=sum(value==0 for value in gains),
        negative_pairs=sum(value<0 for value in gains),
        uncalibrated_pairs=len(unknown),
        total_quality_gain=total_gain,
        mean_quality_gain=(total_gain/len(gains)) if gains else None,
        total_weighted_cost=weighted,
        gain_per_cost=(total_gain/weighted) if weighted not in (None,0) else None,
        regression_cases=regressions,
        uncalibrated_cases=unknown,
        cost_model_id=cost_model.cost_model_id if cost_model else None,
    )
