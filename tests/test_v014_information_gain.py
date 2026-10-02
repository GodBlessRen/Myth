from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.domains.information import InformationResolution
from myth.evaluation_runner import FoundationEvalRunner
from myth.platform.evaluation import (
    EvalObservation,
    EvalVerdict,
    compare_observations,
)
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.runtime import MythRuntime
from myth.strategies import PairedEvalGainEstimator


class InformationGainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.suite=Path(__file__).resolve().parents[1]/"evals"/"foundation-v3.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_paired_resolution_eval_produces_real_quality_delta(self):
        baseline=FoundationEvalRunner.from_path(
            self.suite,
            policy_id="resolution-l0",
            resolution_policy="L0",
        ).run(["resolution-marker-presence"])
        candidate=FoundationEvalRunner.from_path(
            self.suite,
            policy_id="resolution-l1",
            resolution_policy="L1",
        ).run(["resolution-marker-presence"])

        self.assertEqual(baseline["observations"][0]["verdict"],"FAIL")
        self.assertEqual(candidate["observations"][0]["verdict"],"PASS")
        self.assertEqual(baseline["observations"][0]["comparison_key"],"resolution-marker-presence")
        self.assertEqual(candidate["observations"][0]["comparison_key"],"resolution-marker-presence")

        with MythRuntime(self.root) as runtime:
            ledger=SqliteEvaluationLedger(runtime)
            before=ledger.record(baseline,policy_id="resolution-l0")
            after=ledger.record(candidate,policy_id="resolution-l1")
            [pair]=ledger.paired_comparisons(before["eval_run_id"],after["eval_run_id"])

        self.assertEqual(pair.observed_quality_gain,1.0)
        self.assertEqual(pair.baseline_policy_id,"resolution-l0")
        self.assertEqual(pair.candidate_policy_id,"resolution-l1")
        self.assertGreater(pair.cost_delta["context_chars"],0)

    def test_gain_estimator_refuses_arbitrary_cost_scalar_without_weights(self):
        baseline=EvalObservation(
            "case",
            EvalVerdict.FAIL,
            "marker absent",
            {"context_chars":500,"latency_ms":10},
            ("doc:x@digest",),
            policy_id="l0",
            comparison_key="same-source-case",
        )
        candidate=EvalObservation(
            "case",
            EvalVerdict.PASS,
            "marker visible",
            {"context_chars":1800,"latency_ms":12},
            ("doc:x@digest",),
            policy_id="l1",
            comparison_key="same-source-case",
        )
        pair=compare_observations(baseline,candidate)
        estimate=PairedEvalGainEstimator().estimate(
            pair,
            source_ref="doc:x@digest",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
        )
        self.assertTrue(estimate.calibrated)
        self.assertEqual(estimate.quality_gain,1.0)
        self.assertIsNone(estimate.weighted_cost)
        self.assertIsNone(estimate.gain.gain_per_cost)

    def test_gain_per_cost_requires_declared_non_negative_weights(self):
        baseline=EvalObservation(
            "case",
            EvalVerdict.FAIL,
            "before",
            {"context_chars":500,"tool_calls":0},
            policy_id="l0",
            comparison_key="case",
        )
        candidate=EvalObservation(
            "case",
            EvalVerdict.PASS,
            "after",
            {"context_chars":1500,"tool_calls":1},
            policy_id="l1",
            comparison_key="case",
        )
        pair=compare_observations(baseline,candidate)
        estimator=PairedEvalGainEstimator()
        estimate=estimator.estimate(
            pair,
            source_ref="doc:x@d",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
            cost_weights={"context_chars":0.001,"tool_calls":2.0},
        )
        self.assertEqual(estimate.weighted_cost,3.0)
        self.assertAlmostEqual(estimate.gain.gain_per_cost,1/3)
        with self.assertRaises(ValueError):
            estimator.estimate(
                pair,
                source_ref="doc:x@d",
                from_resolution=InformationResolution.L0,
                to_resolution=InformationResolution.L1,
                cost_weights={"context_chars":-1},
            )

    def test_inconclusive_pair_is_explicitly_uncalibrated(self):
        baseline=EvalObservation(
            "case",
            EvalVerdict.INCONCLUSIVE,
            "judge unavailable",
            policy_id="a",
            comparison_key="case",
        )
        candidate=EvalObservation(
            "case",
            EvalVerdict.PASS,
            "candidate passed",
            policy_id="b",
            comparison_key="case",
        )
        pair=compare_observations(baseline,candidate)
        estimate=PairedEvalGainEstimator().estimate(
            pair,
            source_ref="doc:x@d",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
            cost_weights={"latency_ms":1},
        )
        self.assertFalse(estimate.calibrated)
        self.assertIsNone(estimate.quality_gain)
        self.assertIsNone(estimate.gain.gain_per_cost)

    def test_pairing_rejects_different_cases_or_comparison_keys(self):
        left=EvalObservation(
            "a",EvalVerdict.PASS,"ok",policy_id="p1",comparison_key="shared"
        )
        with self.assertRaises(ValueError):
            compare_observations(
                left,
                EvalObservation("b",EvalVerdict.PASS,"ok",policy_id="p2",comparison_key="shared"),
            )
        with self.assertRaises(ValueError):
            compare_observations(
                left,
                EvalObservation("a",EvalVerdict.PASS,"ok",policy_id="p2",comparison_key="different"),
            )

    def test_eval_ledger_rejects_policy_label_mismatch(self):
        result=FoundationEvalRunner.from_path(
            self.suite,
            policy_id="actual-policy",
            resolution_policy="L0",
        ).run(["resolution-marker-presence"])
        with MythRuntime(self.root) as runtime:
            ledger=SqliteEvaluationLedger(runtime)
            with self.assertRaises(ValueError):
                ledger.record(result,policy_id="forged-policy")


if __name__=="__main__":
    unittest.main()
