"""配对固定评测证据的边际增益估计策略。
只比较同 suite/version/case 的观测；成本保持多维，只有显式 CostModel 才归一为标量，不直接控制实时准入或发布。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domains.information import InformationGain, InformationResolution
from ..platform.evaluation import PairedEvalComparison


# 增益、成本与校准证据的纯投影；相似度和置信度不被伪装为质量增益。
@dataclass(frozen=True)
class GainEstimate:
    # gain：附带来源/估计器语义的增益合同。
    gain: InformationGain
    # quality_gain：固定配对题的已测质量差。
    quality_gain: float | None
    # cost_delta：同题共同测量成本维度的差值向量。
    cost_delta: dict[str, float]
    # weighted_cost：显式权重计算的成本；无权重为 None。
    weighted_cost: float | None
    # calibrated：是否有足够配对质量证据；不是实时任务保证。
    calibrated: bool
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str

    # 生成 JSON 可保存的数据投影；保留身份、版本和单位，不在此授予执行或发布权限。
    def serializable(self) -> dict:
        return {
            "source_ref": self.gain.source_ref,
            "from_resolution": (
                self.gain.from_resolution.value if self.gain.from_resolution else None
            ),
            "to_resolution": self.gain.to_resolution.value,
            "estimated_gain": self.gain.estimated_gain,
            "estimated_cost": self.gain.estimated_cost,
            "gain_per_cost": self.gain.gain_per_cost,
            "estimator": self.gain.estimator,
            "quality_gain": self.quality_gain,
            "cost_delta": dict(self.cost_delta),
            "weighted_cost": self.weighted_cost,
            "calibrated": self.calibrated,
            "reason": self.reason,
        }


class PairedEvalGainEstimator:
    """从固定同题配对观测估计边际价值；仅显式权重允许计算单位成本收益。"""

    # estimator_id：增益估计器身份；供报告解释估计语义，不是任务收益真值。
    estimator_id = "paired-eval-v1"

    # 只接受同题配对质量事实；未知 verdict 保留未校准，显式权重才生成 scalar cost。
    def estimate(
        self,
        comparison: PairedEvalComparison,
        *,
        source_ref: str,
        from_resolution: InformationResolution | None,
        to_resolution: InformationResolution,
        cost_weights: Mapping[str, float] | None = None,
    ) -> GainEstimate:
        if comparison.observed_quality_gain is None:
            gain = InformationGain(
                source_ref=source_ref,
                from_resolution=from_resolution,
                to_resolution=to_resolution,
                estimator=self.estimator_id,
            )
            return GainEstimate(
                gain=gain,
                quality_gain=None,
                cost_delta=dict(comparison.cost_delta),
                weighted_cost=None,
                calibrated=False,
                reason="paired verdicts are inconclusive/unsupported; task-value gain is uncalibrated",
            )

        weighted_cost = None
        if cost_weights is not None:
            weighted_cost = 0.0
            for meter, weight in cost_weights.items():
                if not isinstance(weight, (int, float)) or weight < 0:
                    raise ValueError("cost weights must be non-negative numbers")
                weighted_cost += float(weight) * max(
                    0.0, float(comparison.cost_delta.get(meter, 0.0))
                )

        gain = InformationGain(
            source_ref=source_ref,
            from_resolution=from_resolution,
            to_resolution=to_resolution,
            estimated_gain=float(comparison.observed_quality_gain),
            estimated_cost=weighted_cost,
            estimator=self.estimator_id,
        )
        return GainEstimate(
            gain=gain,
            quality_gain=float(comparison.observed_quality_gain),
            cost_delta=dict(comparison.cost_delta),
            weighted_cost=weighted_cost,
            calibrated=True,
            reason=(
                "quality delta comes from paired fixed-case observations; weighted cost uses caller-declared weights"
                if cost_weights is not None
                else "quality delta comes from paired fixed-case observations; cost vector is reported without arbitrary weighting"
            ),
        )
