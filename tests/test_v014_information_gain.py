"""回归边界：同题配对增益与成本语义。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

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


# 同题配对增益与成本语义的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class InformationGainTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.suite = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "foundation-v4.json"
        )

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.tmp.cleanup()

    # 回归断言：同题固定策略配对才计算已测质量差，不能以来源长度冒充增益。
    def test_paired_resolution_eval_produces_real_quality_delta(self):
        baseline = FoundationEvalRunner.from_path(
            self.suite,
            policy_id="resolution-l0",
            resolution_policy="L0",
        ).run(["resolution-marker-presence"])
        candidate = FoundationEvalRunner.from_path(
            self.suite,
            policy_id="resolution-l1",
            resolution_policy="L1",
        ).run(["resolution-marker-presence"])

        self.assertEqual(baseline["observations"][0]["verdict"], "FAIL")
        self.assertEqual(candidate["observations"][0]["verdict"], "PASS")
        self.assertEqual(
            baseline["observations"][0]["comparison_key"], "resolution-marker-presence"
        )
        self.assertEqual(
            candidate["observations"][0]["comparison_key"], "resolution-marker-presence"
        )

        with MythRuntime(self.root) as runtime:
            ledger = SqliteEvaluationLedger(runtime)
            before = ledger.record(baseline, policy_id="resolution-l0")
            after = ledger.record(candidate, policy_id="resolution-l1")
            [pair] = ledger.paired_comparisons(
                before["eval_run_id"], after["eval_run_id"]
            )

        self.assertEqual(pair.observed_quality_gain, 1.0)
        self.assertEqual(pair.baseline_policy_id, "resolution-l0")
        self.assertEqual(pair.candidate_policy_id, "resolution-l1")
        self.assertGreater(pair.cost_delta["context_chars"], 0)

    # 回归断言：缺显式权重只保留成本向量，不发明归一化标量。
    def test_gain_estimator_refuses_arbitrary_cost_scalar_without_weights(self):
        baseline = EvalObservation(
            "case",
            EvalVerdict.FAIL,
            "marker absent",
            {"context_chars": 500, "latency_ms": 10},
            ("doc:x@digest",),
            policy_id="l0",
            comparison_key="same-source-case",
        )
        candidate = EvalObservation(
            "case",
            EvalVerdict.PASS,
            "marker visible",
            {"context_chars": 1800, "latency_ms": 12},
            ("doc:x@digest",),
            policy_id="l1",
            comparison_key="same-source-case",
        )
        pair = compare_observations(baseline, candidate)
        estimate = PairedEvalGainEstimator().estimate(
            pair,
            source_ref="doc:x@digest",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
        )
        self.assertTrue(estimate.calibrated)
        self.assertEqual(estimate.quality_gain, 1.0)
        self.assertIsNone(estimate.weighted_cost)
        self.assertIsNone(estimate.gain.gain_per_cost)

    # 回归断言：显式非负权重及非零成本才允许收益/成本比值。
    def test_gain_per_cost_requires_declared_non_negative_weights(self):
        baseline = EvalObservation(
            "case",
            EvalVerdict.FAIL,
            "before",
            {"context_chars": 500, "tool_calls": 0},
            policy_id="l0",
            comparison_key="case",
        )
        candidate = EvalObservation(
            "case",
            EvalVerdict.PASS,
            "after",
            {"context_chars": 1500, "tool_calls": 1},
            policy_id="l1",
            comparison_key="case",
        )
        pair = compare_observations(baseline, candidate)
        estimator = PairedEvalGainEstimator()
        estimate = estimator.estimate(
            pair,
            source_ref="doc:x@d",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
            cost_weights={"context_chars": 0.001, "tool_calls": 2.0},
        )
        self.assertEqual(estimate.weighted_cost, 3.0)
        self.assertAlmostEqual(estimate.gain.gain_per_cost, 1 / 3)
        with self.assertRaises(ValueError):
            estimator.estimate(
                pair,
                source_ref="doc:x@d",
                from_resolution=InformationResolution.L0,
                to_resolution=InformationResolution.L1,
                cost_weights={"context_chars": -1},
            )

    # 回归断言：不确定 verdict 保留未校准，不能补成零或通过。
    def test_inconclusive_pair_is_explicitly_uncalibrated(self):
        baseline = EvalObservation(
            "case",
            EvalVerdict.INCONCLUSIVE,
            "judge unavailable",
            policy_id="a",
            comparison_key="case",
        )
        candidate = EvalObservation(
            "case",
            EvalVerdict.PASS,
            "candidate passed",
            policy_id="b",
            comparison_key="case",
        )
        pair = compare_observations(baseline, candidate)
        estimate = PairedEvalGainEstimator().estimate(
            pair,
            source_ref="doc:x@d",
            from_resolution=InformationResolution.L0,
            to_resolution=InformationResolution.L1,
            cost_weights={"latency_ms": 1},
        )
        self.assertFalse(estimate.calibrated)
        self.assertIsNone(estimate.quality_gain)
        self.assertIsNone(estimate.gain.gain_per_cost)

    # 回归断言：不同题/版本/条件不能配对，避免跨基线刷分。
    def test_pairing_rejects_different_cases_or_comparison_keys(self):
        left = EvalObservation(
            "a", EvalVerdict.PASS, "ok", policy_id="p1", comparison_key="shared"
        )
        with self.assertRaises(ValueError):
            compare_observations(
                left,
                EvalObservation(
                    "b", EvalVerdict.PASS, "ok", policy_id="p2", comparison_key="shared"
                ),
            )
        with self.assertRaises(ValueError):
            compare_observations(
                left,
                EvalObservation(
                    "a",
                    EvalVerdict.PASS,
                    "ok",
                    policy_id="p2",
                    comparison_key="different",
                ),
            )

    # 回归断言：评测记录的固定 policy 身份与报告不符时拒绝保存。
    def test_eval_ledger_rejects_policy_label_mismatch(self):
        result = FoundationEvalRunner.from_path(
            self.suite,
            policy_id="actual-policy",
            resolution_policy="L0",
        ).run(["resolution-marker-presence"])
        with MythRuntime(self.root) as runtime:
            ledger = SqliteEvaluationLedger(runtime)
            with self.assertRaises(ValueError):
                ledger.record(result, policy_id="forged-policy")


if __name__ == "__main__":
    unittest.main()
