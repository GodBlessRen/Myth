"""EvoOntology 风格的受控演化提名：从 Discovery 真实独立失败推导建议，绝不自动发布。"""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.platform.evaluation_store import SqliteEvaluationLedger


class EvolutionNominationTests(unittest.TestCase):
    """使用真实 Evaluation Ledger 检验去重、Discovery/Final 隔离、候选抑制与只读性。"""

    def setUp(self):
        """创建临时权威 Store 和独立的演化与评测所有者。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.evolution = self.workspace.evolution
        self.ledger = SqliteEvaluationLedger(self.runtime)
        self.policy_id = self.evolution.active()["policy_id"]

    def tearDown(self):
        """关闭持久连接，保证 Case 计数及发布历史不跨测试。"""
        self.runtime.close()
        self.tmp.cleanup()

    def record(self, name, verdicts, *, partition="discovery", complete=True, safety_at=()):
        """按稳定 Case ID 写入当前活动策略的实验结果，而不是伪造提名输出。"""
        observations = [
            {"case_id": f"case-{i}", "verdict": verdict,
             "reason": "fixture result", "metrics": {},
             "evidence_refs": [], "safety_regression": i in safety_at}
            for i, verdict in enumerate(verdicts)
        ]
        return self.ledger.record({
            "suite_id": name, "version": 1,
            "observations": observations, "evaluation_partition": partition,
            "complete_suite": complete, "suite_case_count": len(observations),
            "selected_case_count": len(observations), "report": {},
            "release_gate": {"passed": False},
        }, policy_id=self.policy_id)

    def test_nomination_requires_independent_discovery_failures_and_does_not_create_candidate(self):
        """三例失败跨八道题达到门槛；反复评测相同 Case 不能增加分母。"""
        failures = ["FAIL", "FAIL", "FAIL", "PASS", "PASS", "PASS", "PASS", "PASS"]
        self.record("stable-suite", failures)
        self.record("stable-suite", failures)
        report = self.evolution.nomination_report()
        self.assertTrue(report["due"])
        self.assertEqual(report["reason"], "enough_independent_failures")
        self.assertEqual(report["independent_cases"], 8)
        self.assertEqual(report["failed_cases"], 3)
        self.assertEqual(report["failure_ratio"], 3 / 8)
        self.assertEqual(len(report["evidence_eval_run_ids"]), 1)
        self.assertIn(report["evidence_eval_run_ids"][0],
                      [item["eval_run_id"] for item in self.ledger.list_runs(5)])
        self.assertEqual(self.evolution.candidates(), [])
        self.assertEqual(self.evolution.history(), [])

    def test_final_and_partial_evaluations_cannot_trigger_research(self):
        """Held-out Final 与不完整分母不得反馈到候选搜索，避免评测数据泄漏。"""
        self.record("private-final", ["FAIL"] * 12, partition="final")
        self.record("partial", ["FAIL"] * 12, complete=False)
        report = self.evolution.nomination_report()
        self.assertFalse(report["due"])
        self.assertEqual(report["independent_cases"], 0)

    def test_safety_regression_forces_review_but_never_promotes(self):
        """一次独立安全回归只提升人工审查优先级，不给予自动发布资格。"""
        self.record("safe", ["FAIL"], safety_at=(0,))
        report = self.evolution.nomination_report()
        self.assertTrue(report["due"])
        self.assertEqual(report["reason"], "safety_regression_requires_review")
        self.assertEqual(self.evolution.active()["policy_id"], self.policy_id)
        self.assertEqual(self.evolution.candidates(), [])

    def test_pending_candidate_suppresses_redundant_nomination(self):
        """已有 DRAFT 候选时停止制造新建议，活动策略指针不受影响。"""
        self.record("suite", ["FAIL"] * 8)
        candidate = self.evolution.create_candidate(
            config={"mode": "rule"}, changes=["evaluate a measured alternative"],
        )
        report = self.evolution.nomination_report()
        self.assertFalse(report["due"])
        self.assertEqual(report["reason"], "candidate_already_in_review")
        self.assertEqual(report["candidate_id"], candidate["candidate_id"])
        self.assertEqual(self.evolution.active()["policy_id"], self.policy_id)


if __name__ == "__main__":
    unittest.main()
