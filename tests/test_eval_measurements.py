"""评测成本缺测回归：只使用固定观测和临时 SQLite，不请求任何供应商。

质量 PASS、成本实测零和成本未知是三种事实；效率资格必须来自同题共同测量。
"""
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from myth.platform.evaluation import (
    EvalObservation, EvalVerdict, capability_efficiency_gate,
    compare_observations, eval_report_from_dict, summarize_observations,
)
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.platform.evolution_store import SqliteEvolutionControl
from myth.runtime import MythRuntime


class EvalMeasurementTests(unittest.TestCase):
    """以最小固定题刻画缺测，不用供应商费用或模型自评分制造期望。"""

    def test_empty_observations_have_unknown_cost(self):
        """没有观测就没有测量；空集合的数学和不能作为实测成本。"""
        self.assertIsNone(summarize_observations("missing", []).measured_cost)

    def test_missing_cost_fields_remain_unknown(self):
        """None、空 metrics 和仅有其他维度都不提供标量 cost。"""
        for metrics in (None, {}, {"input_tokens": 12}):
            with self.subTest(metrics=metrics):
                report = summarize_observations(
                    "missing", [EvalObservation("a", EvalVerdict.PASS, "fixed", metrics)]
                )
                self.assertIsNone(report.measured_cost)
                self.assertEqual(report.pass_count, 1)

    def test_explicit_unknown_cost_remains_unknown(self):
        """持久 JSON 的显式 null 与未提供 cost 一样保留未知。"""
        report = summarize_observations(
            "missing", [EvalObservation("a", EvalVerdict.PASS, "fixed", {"cost": None})]
        )
        self.assertIsNone(report.measured_cost)

    def test_measured_zero_is_preserved(self):
        """确实报告的零仍是测量，不能因真假值判断被替换成 None。"""
        report = summarize_observations(
            "zero", [EvalObservation("a", EvalVerdict.PASS, "fixed", {"cost": 0})]
        )
        self.assertEqual(report.measured_cost, 0)

    def test_reported_cost_subtotal_does_not_invent_missing_samples(self):
        """此字段只汇总已报告 cost；未报告的题仍保留在质量完整分母。"""
        report = summarize_observations("subtotal", [
            EvalObservation("a", EvalVerdict.PASS, "fixed", {"cost": 2}),
            EvalObservation("b", EvalVerdict.PASS, "fixed"),
        ])
        self.assertEqual(report.measured_cost, 2)
        self.assertEqual(report.total, 2)

    def test_serialization_preserves_unknown_and_zero(self):
        """持久报告的 JSON null 和整数零都按原事实恢复，读取不重新计费。"""
        for cost in (None, 0):
            with self.subTest(cost=cost):
                report = eval_report_from_dict({"suite_id": "roundtrip", "measured_cost": cost})
                self.assertEqual(report.measured_cost, cost)
                self.assertEqual(eval_report_from_dict(asdict(report)), report)

    def test_missing_paired_cost_cannot_become_efficiency_improvement(self):
        """基准未知、候选实测零没有共同成本，不能被解释为节省。"""
        before = EvalObservation("a", EvalVerdict.PASS, "fixed", {"cost": None}, policy_id="base")
        after = EvalObservation("a", EvalVerdict.PASS, "fixed", {"cost": 0}, policy_id="candidate")
        pair = compare_observations(before, after)
        self.assertEqual(pair.cost_delta, {})
        passed, reason, delta = capability_efficiency_gate(
            summarize_observations("paired", [before]),
            summarize_observations("paired", [after]), [pair],
        )
        self.assertFalse(passed)
        self.assertIn("no common measured", reason)
        self.assertEqual(delta, {})

    def test_persisted_unknown_cost_holds_candidate_and_blocks_promote(self):
        """真实账本往返与发布入口都保留缺测；质量全过也不能绕过效率门。"""
        with tempfile.TemporaryDirectory() as directory, MythRuntime(Path(directory)) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            candidate = evolution.create_candidate(
                candidate_id="unknown-cost", config={"mode": "rule"}, changes=["fixed measurement probe"],
            )
            ledger = SqliteEvaluationLedger(runtime)
            runs = []
            # 两条完整 final 结果固定同题/version；唯一差别是 policy 身份，成本都未测。
            for policy_id in (candidate["baseline_policy_id"], candidate["candidate_id"]):
                observation = EvalObservation("a", EvalVerdict.PASS, "fixed", policy_id=policy_id)
                report = summarize_observations("unknown-cost-suite", [observation])
                result = {
                    "suite_id": report.suite_id, "version": 1, "policy_id": policy_id,
                    "evaluation_partition": "final", "suite_case_count": 1,
                    "selected_case_count": 1, "complete_suite": True, "report": asdict(report),
                    "release_gate": {"passed": True, "reason": "fixed quality pass"},
                    "observations": [asdict(observation)],
                }
                recorded = ledger.record(result, policy_id=policy_id)
                self.assertIsNone(recorded["report"]["measured_cost"])
                runs.append(recorded["eval_run_id"])
            evaluated = evolution.attach_evaluation(
                candidate["candidate_id"], baseline_eval_run_id=runs[0], candidate_eval_run_id=runs[1],
            )
            self.assertEqual(evaluated["status"], "HOLD")
            self.assertFalse(evaluated["efficiency_gate"]["passed"])
            with self.assertRaisesRegex(ValueError, "ELIGIBLE"):
                evolution.promote(candidate["candidate_id"])
