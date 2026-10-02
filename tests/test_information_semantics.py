from __future__ import annotations

import unittest

from myth.domains.coordination import StrategyState, default_strategies
from myth.domains.information import (
    InformationDelta,
    InformationGain,
    InformationResolution,
    InformationView,
    IntentPick,
    IntentRoute,
)


class InformationSemanticsTests(unittest.TestCase):
    def test_information_resolution_means_granularity_not_sufficiency(self):
        self.assertEqual(
            [item.value for item in InformationResolution],
            ["L0", "L1", "L2"],
        )
        view = InformationView(
            source_ref="memory:42",
            resolution=InformationResolution.L0,
            content="compact abstract",
            provenance_ref="event:9",
            token_estimate=12,
        )
        self.assertEqual(view.resolution, InformationResolution.L0)
        self.assertEqual(view.provenance_ref, "event:9")

    def test_information_delta_records_change_without_claiming_value(self):
        delta = InformationDelta(
            added=("fact:new",),
            updated=("fact:changed",),
            conflicted=("fact:conflict",),
        )
        self.assertTrue(delta.changed)
        self.assertEqual(delta.removed, ())

    def test_information_gain_does_not_fake_a_score_without_estimator(self):
        unknown = InformationGain(
            source_ref="memory:42",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
        )
        self.assertIsNone(unknown.estimated_gain)
        self.assertIsNone(unknown.gain_per_cost)

        measured = InformationGain(
            source_ref="memory:42",
            from_resolution=InformationResolution.L1,
            to_resolution=InformationResolution.L2,
            estimated_gain=0.6,
            estimated_cost=0.2,
            estimator="eval-calibrated-demo",
        )
        self.assertAlmostEqual(measured.gain_per_cost, 3.0)

    def test_intent_pick_selects_processing_path_not_execution_authority(self):
        pick = IntentPick(
            route=IntentRoute.LOCAL_RETRIEVAL,
            objective="find an existing local fact",
            confidence=0.97,
            reason="exact local knowledge lookup",
        )
        self.assertEqual(pick.route, IntentRoute.LOCAL_RETRIEVAL)
        self.assertNotIn("ticket", (pick.metadata or {}))

    def test_information_strategy_maturity_matches_connected_paths(self):
        registry = default_strategies()
        self.assertEqual(registry.get("intent_pick").state, StrategyState.CONNECTED)
        self.assertEqual(registry.get("information_resolution").state, StrategyState.EXISTS)
        self.assertEqual(registry.get("information_gain").state, StrategyState.EXISTS)


if __name__ == "__main__":
    unittest.main()
