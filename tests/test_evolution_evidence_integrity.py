"""Evolution 发布证据完整性回归：存储事实而不是传入的 gate 决定晋升。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from myth.platform.evaluation import EvalObservation, EvalVerdict, summarize_observations
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.platform.evolution_store import SqliteEvolutionControl
from myth.runtime import MythRuntime


class EvolutionEvidenceIntegrityTests(unittest.TestCase):
    """临时 SQLite 上固定完整观测、成本计量与发布前修改，绝不调用真实 Provider。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.evolution = SqliteEvolutionControl(self.runtime)
        self.ledger = SqliteEvaluationLedger(self.runtime)
        self.candidate = self.evolution.create_candidate(
            candidate_id="integrity-candidate", config={"mode": "rule"}, changes=["integrity probe"]
        )

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def record(self, policy, *, case_id="fixed-case", tokens=10, verdict=EvalVerdict.PASS):
        observation = EvalObservation(
            case_id, verdict, "fixed result", {"input_tokens": tokens, "tool_calls": 1},
            policy_id=policy, comparison_key=case_id,
        )
        report = summarize_observations("integrity-v1", [observation])
        return self.ledger.record(
            {
                "suite_id": "integrity-v1", "version": 1, "policy_id": policy,
                "suite_case_count": 1, "selected_case_count": 1, "complete_suite": True,
                "evaluation_partition": "final",
                "report": asdict(report),
                "release_gate": {"passed": verdict is EvalVerdict.PASS, "reason": "fixture"},
                "observations": [asdict(observation)],
            },
            policy_id=policy,
        )

    def pair(self):
        baseline = self.record(self.candidate["baseline_policy_id"])
        tested = self.record(self.candidate["candidate_id"])
        return baseline["eval_run_id"], tested["eval_run_id"]

    def test_baseline_and_candidate_case_sets_must_match(self):
        baseline = self.record(self.candidate["baseline_policy_id"], case_id="case-a")
        tested = self.record(self.candidate["candidate_id"], case_id="case-b")
        with self.assertRaisesRegex(ValueError, "identical fixed case identities"):
            self.evolution.attach_evaluation(
                self.candidate["candidate_id"],
                baseline_eval_run_id=baseline["eval_run_id"],
                candidate_eval_run_id=tested["eval_run_id"],
            )

    def test_report_cannot_hide_failed_observation(self):
        baseline_id, tested_id = self.pair()
        self.runtime.store.db.execute(
            "UPDATE evaluation_observations SET verdict='FAIL' WHERE eval_run_id=?",
            (tested_id,),
        )
        with self.assertRaisesRegex(ValueError, "report disagrees"):
            self.evolution.attach_evaluation(
                self.candidate["candidate_id"],
                baseline_eval_run_id=baseline_id,
                candidate_eval_run_id=tested_id,
            )

    def test_complete_flag_cannot_hide_missing_cases(self):
        baseline_id, tested_id = self.pair()
        self.runtime.store.db.execute(
            "UPDATE evaluation_runs SET suite_case_count=2 WHERE eval_run_id=?",
            (tested_id,),
        )
        with self.assertRaisesRegex(ValueError, "incomplete or inconsistent"):
            self.evolution.attach_evaluation(
                self.candidate["candidate_id"],
                baseline_eval_run_id=baseline_id,
                candidate_eval_run_id=tested_id,
            )

    def test_non_finite_cost_cannot_bypass_pareto_gate(self):
        baseline_id, tested_id = self.pair()
        self.runtime.store.db.execute(
            "UPDATE evaluation_observations SET metrics_json=? WHERE eval_run_id=?",
            ('{"input_tokens":NaN,"tool_calls":1}', tested_id),
        )
        with self.assertRaisesRegex(ValueError, "non-finite cost"):
            self.evolution.attach_evaluation(
                self.candidate["candidate_id"],
                baseline_eval_run_id=baseline_id,
                candidate_eval_run_id=tested_id,
            )

    def test_evidence_mutation_after_eligibility_blocks_promotion(self):
        baseline_id, tested_id = self.pair()
        eligible = self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
        )
        self.assertEqual(eligible["status"], "ELIGIBLE")
        self.runtime.store.db.execute(
            "UPDATE evaluation_runs SET selected_case_count=0 WHERE eval_run_id=?",
            (tested_id,),
        )
        with self.assertRaisesRegex(ValueError, "incomplete or inconsistent"):
            self.evolution.promote(self.candidate["candidate_id"])
        self.assertEqual(self.evolution.active()["policy_id"], self.candidate["baseline_policy_id"])
        self.assertEqual(self.evolution.history(), [])


if __name__ == "__main__":
    unittest.main()
