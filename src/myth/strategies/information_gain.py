"""Eval-calibrated Information Gain estimation.

Gain is derived only from paired observations of the same case/comparison key.
No similarity score, classifier confidence, or retrieval score is accepted as
task-value evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domains.information import InformationGain, InformationResolution
from ..platform.evaluation import PairedEvalComparison


@dataclass(frozen=True)
class GainEstimate:
    gain: InformationGain
    quality_gain: float | None
    cost_delta: dict[str, float]
    weighted_cost: float | None
    calibrated: bool
    reason: str

    def serializable(self) -> dict:
        return {
            "source_ref": self.gain.source_ref,
            "from_resolution": self.gain.from_resolution.value if self.gain.from_resolution else None,
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
    """Convert one paired eval comparison into a declared gain estimate."""

    estimator_id = "paired-eval-v1"

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
            gain=InformationGain(
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

        weighted_cost=None
        if cost_weights is not None:
            weighted_cost=0.0
            for meter,weight in cost_weights.items():
                if not isinstance(weight,(int,float)) or weight < 0:
                    raise ValueError("cost weights must be non-negative numbers")
                weighted_cost += float(weight) * max(0.0,float(comparison.cost_delta.get(meter,0.0)))

        gain=InformationGain(
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
