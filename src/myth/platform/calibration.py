"""配对增益证据的纯校准矩阵。
按 Resolution/backend 覆盖汇总固定观测，不填造缺失证据；发布资格要求明确测量范围和完整覆盖。"""

from __future__ import annotations

from dataclasses import dataclass

from .cost_model import CostModel
from .evaluation import PairedEvalComparison


# 完整配对证据的校准汇总；覆盖率和回归题同时可见，不隐藏缺测。
@dataclass(frozen=True)
class GainCalibrationMatrix:
    # total_pairs：固定比较中的全部配对题数。
    total_pairs: int
    # calibrated_pairs：双方质量均可解释的配对题数。
    calibrated_pairs: int
    # positive_pairs：观测质量差大于零的题数。
    positive_pairs: int
    # zero_pairs：观测质量差等于零的题数。
    zero_pairs: int
    # negative_pairs：观测到质量退步的题数；不能只报告平均收益。
    negative_pairs: int
    # uncalibrated_pairs：无法测量增益的配对题数。
    uncalibrated_pairs: int
    # total_quality_gain：全部已校准题的质量差总和。
    total_quality_gain: float
    # mean_quality_gain：已校准题的平均差；无样本为 None。
    mean_quality_gain: float | None
    # total_weighted_cost：显式 CostModel 的正向额外成本总和；无模型为 None。
    total_weighted_cost: float | None
    # gain_per_cost：已测增益/非零显式成本；未知/零不造比值。
    gain_per_cost: float | None
    # regression_cases：观测退步的固定题身份，供定位。
    regression_cases: tuple[str, ...]
    # uncalibrated_cases：缺测或不确定配对的固定题身份。
    uncalibrated_cases: tuple[str, ...]
    # cost_model_id：显式成本权重合同身份；不能被不同内容复用。
    cost_model_id: str | None

    # 计算已校准对数/全部对数；无样本为零，不能造满覆盖。
    @property
    def coverage(self) -> float:
        return (
            0.0 if self.total_pairs == 0 else self.calibrated_pairs / self.total_pairs
        )

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict:
        return {
            "total_pairs": self.total_pairs,
            "calibrated_pairs": self.calibrated_pairs,
            "positive_pairs": self.positive_pairs,
            "zero_pairs": self.zero_pairs,
            "negative_pairs": self.negative_pairs,
            "uncalibrated_pairs": self.uncalibrated_pairs,
            "coverage": self.coverage,
            "total_quality_gain": self.total_quality_gain,
            "mean_quality_gain": self.mean_quality_gain,
            "total_weighted_cost": self.total_weighted_cost,
            "gain_per_cost": self.gain_per_cost,
            "regression_cases": list(self.regression_cases),
            "uncalibrated_cases": list(self.uncalibrated_cases),
            "cost_model_id": self.cost_model_id,
        }

    # 要求足够配对、必要完整覆盖且无负增益题；给资格，不发发布命令。
    def promotion_gate(
        self, *, min_pairs: int = 1, require_full_coverage: bool = True
    ) -> tuple[bool, str]:
        if self.calibrated_pairs < min_pairs:
            return (
                False,
                f"only {self.calibrated_pairs} calibrated pairs; require {min_pairs}",
            )
        if require_full_coverage and self.uncalibrated_pairs:
            return False, "uncalibrated paired cases remain"
        if self.negative_pairs:
            return False, "candidate regresses one or more fixed cases"
        return True, "paired calibration gate passed"


# 汇总同题配对的正/零/负/未知增益；只有显式 CostModel 才计算加权成本。
def build_calibration_matrix(
    comparisons: list[PairedEvalComparison] | tuple[PairedEvalComparison, ...],
    cost_model: CostModel | None = None,
) -> GainCalibrationMatrix:
    values = tuple(comparisons)
    calibrated = [item for item in values if item.observed_quality_gain is not None]
    gains = [float(item.observed_quality_gain) for item in calibrated]
    regressions = tuple(
        item.case_id for item in calibrated if float(item.observed_quality_gain) < 0
    )
    unknown = tuple(
        item.case_id for item in values if item.observed_quality_gain is None
    )
    weighted = None
    if cost_model is not None:
        weighted = sum(cost_model.weighted_cost(item.cost_delta) for item in calibrated)
    total_gain = sum(gains)
    return GainCalibrationMatrix(
        total_pairs=len(values),
        calibrated_pairs=len(calibrated),
        positive_pairs=sum(value > 0 for value in gains),
        zero_pairs=sum(value == 0 for value in gains),
        negative_pairs=sum(value < 0 for value in gains),
        uncalibrated_pairs=len(unknown),
        total_quality_gain=total_gain,
        mean_quality_gain=(total_gain / len(gains)) if gains else None,
        total_weighted_cost=weighted,
        gain_per_cost=(total_gain / weighted) if weighted not in (None, 0) else None,
        regression_cases=regressions,
        uncalibrated_cases=unknown,
        cost_model_id=cost_model.cost_model_id if cost_model else None,
    )
