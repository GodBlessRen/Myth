"""Evolution 发布证据完整性回归：存储事实而不是传入的 gate 决定晋升。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.platform.evaluation import EvalObservation, EvalVerdict, summarize_observations
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.platform.calibration import build_calibration_matrix
from myth.platform.cost_model import CostModel, SqliteCostModelRegistry
from myth.platform.evolution_store import SqliteEvolutionControl
from myth.runtime import MythRuntime


class EvolutionEvidenceIntegrityTests(unittest.TestCase):
    """临时 SQLite 上固定完整观测、成本计量与发布前修改，绝不调用真实 Provider。"""

    # 准备独立临时仓储和未发布候选，避免测试共享状态。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.evolution = SqliteEvolutionControl(self.runtime)
        self.ledger = SqliteEvaluationLedger(self.runtime)
        self.candidate = self.evolution.create_candidate(
            candidate_id="integrity-candidate", config={"mode": "rule"}, changes=["integrity probe"]
        )

    # 关闭本例 Runtime 并销毁临时文件，不保留实验库。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 写入一条固定策略逐题结论并冻结完整分母，作为持久证据夹具。
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

    # 创建同 Suite、同 Case 的两条评测运行并返回其持久身份。
    def pair(self):
        baseline = self.record(self.candidate["baseline_policy_id"])
        tested = self.record(self.candidate["candidate_id"])
        return baseline["eval_run_id"], tested["eval_run_id"]

    # 不同题号即使数量一致，也不能借助交集得到发布资格。
    def test_baseline_and_candidate_case_sets_must_match(self):
        baseline = self.record(self.candidate["baseline_policy_id"], case_id="case-a")
        tested = self.record(self.candidate["candidate_id"], case_id="case-b")
        with self.assertRaisesRegex(ValueError, "identical fixed case identities"):
            self.evolution.attach_evaluation(
                self.candidate["candidate_id"],
                baseline_eval_run_id=baseline["eval_run_id"],
                candidate_eval_run_id=tested["eval_run_id"],
            )

    # 落库后恶意将 PASS 改为 FAIL，缓存报告不得掩盖真实结论。
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

    # 把声明的评测题总数加一，防止完整标记掩盖缺失记录。
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

    # 非法非有限成本不得通过数值比较绕过效率回归门。
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

    # 已获得资格不代表永久可发布；事务内须拒绝被修改的证据。
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


    # 题数、报告、PASS 标记全都不变，仅改变实测成本时也必须撤销旧晋级资格。
    def test_coherent_metric_change_after_qualification_blocks_promotion(self):
        baseline_id, tested_id = self.pair()
        eligible = self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
        )
        self.assertTrue(eligible["efficiency_gate"]["evidence_seal"].startswith("sha256:"))
        self.runtime.store.db.execute(
            "UPDATE evaluation_observations SET metrics_json=? WHERE eval_run_id=?",
            ('{"input_tokens":9,"tool_calls":1}', tested_id),
        )
        with self.assertRaisesRegex(ValueError, "release evidence changed"):
            self.evolution.promote(self.candidate["candidate_id"])
        self.assertEqual(self.evolution.history(), [])

    # 已批准的规则策略不能在发布前偷换配置，即使同一套评测题全部仍然 PASS。
    def test_policy_config_change_after_qualification_blocks_promotion(self):
        baseline_id, tested_id = self.pair()
        self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
        )
        self.runtime.store.db.execute(
            "UPDATE policy_candidates SET config_json=? WHERE candidate_id=?",
            ('{"mode":"fixed","resolution":"L1"}', self.candidate["candidate_id"]),
        )
        with self.assertRaisesRegex(ValueError, "release evidence changed"):
            self.evolution.promote(self.candidate["candidate_id"])

    # 人工配置的成本权重属于同一晋级证据，旧权重不能被重新解释成新成本。
    def test_cost_model_change_after_qualification_blocks_promotion(self):
        registry = SqliteCostModelRegistry(self.runtime)
        registry.put(CostModel("sealed-cost-model", 1, {"input_tokens": 1.0}))
        baseline_id, tested_id = self.pair()
        self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
            cost_model_id="sealed-cost-model",
        )
        self.runtime.store.db.execute(
            "UPDATE cost_models SET weights_json=? WHERE cost_model_id=?",
            ('{"input_tokens":2.0}', "sealed-cost-model"),
        )
        with self.assertRaisesRegex(ValueError, "release evidence changed"):
            self.evolution.promote(self.candidate["candidate_id"])

    # 校准开始后即使结果字段全部自洽，事务内也必须发现证据已换，不提交过时资格。
    def test_metric_change_during_assessment_is_detected_before_commit(self):
        baseline_id, tested_id = self.pair()
        calls = []

        def mutate_during_calibration(*args, **kwargs):
            calls.append("mutated")
            self.runtime.store.db.execute(
                "UPDATE evaluation_observations SET metrics_json=? WHERE eval_run_id=?",
                ('{"input_tokens":8,"tool_calls":1}', tested_id),
            )
            return build_calibration_matrix(*args, **kwargs)

        with patch(
            "myth.platform.evolution_store.build_calibration_matrix",
            side_effect=mutate_during_calibration,
        ):
            with self.assertRaisesRegex(ValueError, "changed during evaluation assessment"):
                self.evolution.attach_evaluation(
                    self.candidate["candidate_id"],
                    baseline_eval_run_id=baseline_id,
                    candidate_eval_run_id=tested_id,
                )
        self.assertEqual(calls, ["mutated"])
        self.assertEqual(self.evolution.candidate(self.candidate["candidate_id"])["status"], "DRAFT")

    # 当最终集在异步评估窗口被放入 discovery 后，资格提交必须重新检查污染事实。
    def test_late_discovery_contamination_blocks_attachment(self):
        baseline_id, tested_id = self.pair()

        def leak_during_calibration(*args, **kwargs):
            self.runtime.store.db.execute(
                "UPDATE evaluation_runs SET evaluation_partition='discovery' "
                "WHERE eval_run_id=?",
                (tested_id,),
            )
            return build_calibration_matrix(*args, **kwargs)

        with patch(
            "myth.platform.evolution_store.build_calibration_matrix",
            side_effect=leak_during_calibration,
        ):
            with self.assertRaisesRegex(ValueError, "final evaluation partition"):
                self.evolution.attach_evaluation(
                    self.candidate["candidate_id"],
                    baseline_eval_run_id=baseline_id,
                    candidate_eval_run_id=tested_id,
                )
        self.assertEqual(self.evolution.candidate(self.candidate["candidate_id"])["status"], "DRAFT")

    # sealed candidate 的证据和成本可以跨进程重启复核；发布历史仍保留原始指纹。
    def test_sealed_evidence_promotes_after_restart_and_survives_rollback(self):
        baseline_id, tested_id = self.pair()
        eligible = self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
        )
        seal = eligible["efficiency_gate"]["evidence_seal"]
        with MythRuntime(Path(self.tmp.name)) as reopened_runtime:
            reopened = SqliteEvolutionControl(reopened_runtime)
            promoted = reopened.promote(self.candidate["candidate_id"])
            self.assertEqual(promoted["active"]["policy_id"], self.candidate["candidate_id"])
            self.assertEqual(reopened.history()[0]["evidence"]["efficiency_gate"]["evidence_seal"], seal)
            rolled = reopened.rollback(reason="test explicit rollback")
            self.assertEqual(rolled["active"]["policy_id"], self.candidate["baseline_policy_id"])
            self.assertEqual(rolled["history"][0]["action"], "ROLLBACK")

    # 无指纹的旧 ELIGIBLE 快照不能绕过新版发布门，应重新绑定并校准评测。
    def test_unsealed_eligible_candidate_fails_closed(self):
        baseline_id, tested_id = self.pair()
        self.evolution.attach_evaluation(
            self.candidate["candidate_id"],
            baseline_eval_run_id=baseline_id,
            candidate_eval_run_id=tested_id,
        )
        self.runtime.store.db.execute(
            "UPDATE policy_candidates SET efficiency_gate_json=? WHERE candidate_id=?",
            ('{"passed":true,"reason":"old gate","cost_delta":{}}', self.candidate["candidate_id"]),
        )
        with self.assertRaisesRegex(ValueError, "requires sealed evaluation evidence"):
            self.evolution.promote(self.candidate["candidate_id"])

    # min_pairs 是能力下限而非任意旁路开关；零、负数和布尔值都不能发布。
    def test_invalid_min_pairs_cannot_disable_release_gate(self):
        baseline_id, tested_id = self.pair()
        for value in (0, -1, True):
            with self.subTest(min_pairs=value):
                with self.assertRaisesRegex(ValueError, "at least one calibrated pair"):
                    self.evolution.attach_evaluation(
                        self.candidate["candidate_id"],
                        baseline_eval_run_id=baseline_id,
                        candidate_eval_run_id=tested_id,
                        min_pairs=value,
                    )

if __name__ == "__main__":
    unittest.main()
