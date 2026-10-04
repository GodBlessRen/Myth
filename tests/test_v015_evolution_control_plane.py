"""回归边界：策略发布资格、版本固定与显式回退。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from myth.evaluation_runner import FoundationEvalRunner
from myth.platform.calibration import build_calibration_matrix
from myth.platform.cost_model import CostModel, SqliteCostModelRegistry
from myth.platform.evaluation import EvalObservation, EvalVerdict, compare_observations
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.platform.evolution_store import SqliteEvolutionControl
from myth.runtime import MythRuntime
from myth.workspace import Workspace


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "ollama_url": "http://127.0.0.1:11434",
    "max_steps": 6,
    "max_output_tokens": 512,
    "thinking": False,
}


# 策略发布资格、版本固定与显式回退的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class EvolutionControlPlaneTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.suite = self.root / "release-suite.json"
        self.suite.write_text(
            json.dumps(
                {
                    "suite_id": "release-mini-v1",
                    "version": 1,
                    "principle": "full fixed suite required for promotion",
                    "cases": [
                        {
                            "case_id": "intent-arithmetic-local",
                            "category": "intent",
                            "input": {"text": "计算 2+3*4"},
                            "expected": {
                                "route": "deterministic",
                                "answer": "14",
                                "model_calls": 0,
                            },
                        },
                        {
                            "case_id": "resolution-agent-l0",
                            "category": "information_resolution",
                            "input": {"text": "帮我分析一个新的产品方案。"},
                            "expected": {"route": "agent", "resolution": "L0"},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.tmp.cleanup()

    # 策略发布资格、版本固定与显式回退的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def _record_pair(self, runtime, candidate_id, config):
        evolution = SqliteEvolutionControl(runtime)
        baseline = evolution.policy(
            evolution.candidate(candidate_id)["baseline_policy_id"]
        )
        baseline_result = FoundationEvalRunner.from_path(
            self.suite,
            policy_id=baseline["policy_id"],
            policy_config=baseline["config"],
        ).run()
        candidate_result = FoundationEvalRunner.from_path(
            self.suite,
            policy_id=candidate_id,
            policy_config=config,
        ).run()
        ledger = SqliteEvaluationLedger(runtime)
        before = ledger.record(baseline_result, policy_id=baseline["policy_id"])
        after = ledger.record(candidate_result, policy_id=candidate_id)
        return before, after

    # 回归断言：成本权重合同不可同身份改写；矩阵保留逐题事实，不只报平均。
    def test_cost_model_is_versioned_immutable_and_matrix_keeps_case_facts(self):
        with MythRuntime(self.root) as runtime:
            registry = SqliteCostModelRegistry(runtime)
            model = CostModel(
                "context-cost-v1",
                1,
                {"context_chars": 0.001, "tool_calls": 2.0},
                "explicit test weights",
            )
            registry.put(model)
            self.assertEqual(registry.get("context-cost-v1")["version"], 1)
            with self.assertRaises(ValueError):
                registry.put(
                    CostModel("context-cost-v1", 2, {"context_chars": 0.1}, "changed")
                )

        before = EvalObservation(
            "case",
            EvalVerdict.FAIL,
            "before",
            {"context_chars": 500, "tool_calls": 0},
            policy_id="a",
            comparison_key="case",
        )
        after = EvalObservation(
            "case",
            EvalVerdict.PASS,
            "after",
            {"context_chars": 1500, "tool_calls": 1},
            policy_id="b",
            comparison_key="case",
        )
        matrix = build_calibration_matrix(
            [compare_observations(before, after)],
            CostModel(
                "context-cost-v1", 1, {"context_chars": 0.001, "tool_calls": 2.0}
            ),
        )
        self.assertEqual(matrix.positive_pairs, 1)
        self.assertEqual(matrix.negative_pairs, 0)
        self.assertEqual(matrix.total_weighted_cost, 3.0)
        self.assertAlmostEqual(matrix.gain_per_cost, 1 / 3)
        self.assertTrue(matrix.promotion_gate(min_pairs=1)[0])

    # 回归断言：筛选评测保持 partial，不能获得完整发布资格。
    def test_partial_suite_cannot_be_used_as_promotion_evidence(self):
        with MythRuntime(self.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            candidate = evolution.create_candidate(
                candidate_id="policy-partial",
                config={"mode": "rule"},
                changes=["candidate exists only to test completeness gate"],
            )
            baseline = evolution.policy(candidate["baseline_policy_id"])
            base_result = FoundationEvalRunner.from_path(
                self.suite,
                policy_id=baseline["policy_id"],
                policy_config=baseline["config"],
            ).run(["intent-arithmetic-local"])
            candidate_result = FoundationEvalRunner.from_path(
                self.suite,
                policy_id=candidate["candidate_id"],
                policy_config=candidate["config"],
            ).run(["intent-arithmetic-local"])
            ledger = SqliteEvaluationLedger(runtime)
            before = ledger.record(base_result, policy_id=baseline["policy_id"])
            after = ledger.record(candidate_result, policy_id=candidate["candidate_id"])
            self.assertFalse(before["complete_suite"])
            with self.assertRaises(ValueError):
                evolution.attach_evaluation(
                    candidate["candidate_id"],
                    baseline_eval_run_id=before["eval_run_id"],
                    candidate_eval_run_id=after["eval_run_id"],
                )

    # 回归断言：即使候选完整通过质量 gate，只要同题已测成本出现 Pareto 回归，就不能进入 ELIGIBLE。
    def test_cost_regression_blocks_candidate_before_promote(self):
        with MythRuntime(self.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            candidate = evolution.create_candidate(
                candidate_id="policy-cost-regression",
                config={"mode": "rule"},
                changes=["exercise capability and efficiency release gate"],
            )
            ledger = SqliteEvaluationLedger(runtime)
            suite_id = "cost-gate-v1"
            report = {
                "suite_id": suite_id,
                "pass_count": 1,
                "fail_count": 0,
                "inconclusive_count": 0,
                "safety_regressions": 0,
                "measured_cost": 0,
                "unsupported_count": 0,
            }
            # 构造同一固定题的完整评测结果，只改变明确的 input_tokens 成本维度。
            def result(policy_id, input_tokens):
                return {
                    "suite_id": suite_id,
                    "version": 1,
                    "policy_id": policy_id,
                    "suite_case_count": 1,
                    "selected_case_count": 1,
                    "complete_suite": True,
                    "report": report,
                    "release_gate": {"passed": True, "reason": "quality gate passed"},
                    "observations": [
                        {
                            "case_id": "case-1",
                            "verdict": "PASS",
                            "reason": "fixed pass",
                            "metrics": {"input_tokens": input_tokens, "tool_calls": 1},
                            "evidence_refs": ["eval:case-1"],
                            "comparison_key": "case-1",
                        }
                    ],
                }
            before = ledger.record(
                result(candidate["baseline_policy_id"], 100),
                policy_id=candidate["baseline_policy_id"],
            )
            after = ledger.record(
                result(candidate["candidate_id"], 130),
                policy_id=candidate["candidate_id"],
            )
            evaluated = evolution.attach_evaluation(
                candidate["candidate_id"],
                baseline_eval_run_id=before["eval_run_id"],
                candidate_eval_run_id=after["eval_run_id"],
            )
            self.assertEqual(evaluated["status"], "HOLD")
            self.assertFalse(evaluated["efficiency_gate"]["passed"])
            self.assertIn("Pareto", evaluated["efficiency_gate"]["reason"])
            with self.assertRaises(ValueError):
                evolution.promote(candidate["candidate_id"])

    # 回归断言：显式发布只改变未来 Turn，旧快照固定策略，回退也保留历史。
    def test_candidate_promote_freezes_future_turn_policy_and_rollback(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            workspace.repository.save_settings(SETTINGS)
            sid = workspace.repository.create_session()["id"]
            first = workspace.repository.create_turn(
                sid, "第一个请求", "v015-before-promote"
            )
            first_snapshot = workspace.repository.turn(first["run_id"])["snapshot"]
            self.assertEqual(
                first_snapshot["policy_bindings"]["information_resolution"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            workspace.repository.block(
                first["run_id"], "FAILED", "test closes first turn"
            )

            evolution = SqliteEvolutionControl(runtime)
            candidate = evolution.create_candidate(
                candidate_id="policy-rule-v2",
                config={"mode": "rule"},
                changes=[
                    "version the same rule policy through the release control plane"
                ],
            )
            before, after = self._record_pair(
                runtime, candidate["candidate_id"], candidate["config"]
            )
            evaluated = evolution.attach_evaluation(
                candidate["candidate_id"],
                baseline_eval_run_id=before["eval_run_id"],
                candidate_eval_run_id=after["eval_run_id"],
                min_pairs=2,
            )
            self.assertEqual(evaluated["status"], "ELIGIBLE")
            self.assertEqual(evaluated["calibration"]["negative_pairs"], 0)
            self.assertTrue(evaluated["efficiency_gate"]["passed"])
            promoted = evolution.promote(candidate["candidate_id"])
            self.assertEqual(promoted["active"]["policy_id"], candidate["candidate_id"])
            self.assertEqual(promoted["active"]["revision"], 2)

            # A new composition/admission sees the promoted pointer.
            workspace2 = Workspace(runtime)
            second = workspace2.repository.create_turn(
                sid, "第二个请求", "v015-after-promote"
            )
            second_snapshot = workspace2.repository.turn(second["run_id"])["snapshot"]
            self.assertEqual(
                second_snapshot["policy_bindings"]["information_resolution"],
                candidate["candidate_id"],
            )
            # Existing durable Turn evidence did not change.
            self.assertEqual(
                workspace.repository.turn(first["run_id"])["snapshot"][
                    "policy_bindings"
                ]["information_resolution"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            workspace2.repository.block(
                second["run_id"], "FAILED", "test closes second turn"
            )

            rolled = evolution.rollback(reason="test rollback")
            self.assertEqual(
                rolled["active"]["policy_id"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            self.assertEqual(rolled["active"]["revision"], 3)
            self.assertEqual(rolled["history"][0]["action"], "ROLLBACK")

    # 回归断言：旧 baseline 候选不能覆盖已经变化的活动指针。
    def test_stale_candidate_cannot_overwrite_new_active_policy(self):
        with MythRuntime(self.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            one = evolution.create_candidate(
                candidate_id="policy-one", config={"mode": "rule"}, changes=["one"]
            )
            two = evolution.create_candidate(
                candidate_id="policy-two", config={"mode": "rule"}, changes=["two"]
            )
            for candidate in (one, two):
                before, after = self._record_pair(
                    runtime, candidate["candidate_id"], candidate["config"]
                )
                evolution.attach_evaluation(
                    candidate["candidate_id"],
                    baseline_eval_run_id=before["eval_run_id"],
                    candidate_eval_run_id=after["eval_run_id"],
                    min_pairs=2,
                )
            evolution.promote(one["candidate_id"])
            with self.assertRaises(ValueError):
                evolution.promote(two["candidate_id"])

    # 两个连接同时到达发布写事务；只能一个以相同 baseline 发布，另一个须读到已变化事实。
    def test_concurrent_promotions_recheck_under_write_lock(self):
        with MythRuntime(self.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            ids = ["concurrent-one", "concurrent-two"]
            for cid in ids:
                candidate = evolution.create_candidate(candidate_id=cid, config={"mode": "rule"}, changes=[cid])
                before, after = self._record_pair(runtime, cid, candidate["config"])
                evolution.attach_evaluation(cid, baseline_eval_run_id=before["eval_run_id"],
                    candidate_eval_run_id=after["eval_run_id"], min_pairs=2)
        gate = threading.Barrier(2)
        outcomes = []

        # 每线程独立 SQLite 连接；屏障固定在 BEGIN 前，避免靠概率测试竞争。
        def publish(cid):
            with MythRuntime(self.root) as runtime:
                evolution = SqliteEvolutionControl(runtime)
                transaction = runtime.store.tx

                # 同步开始写事务，事务内实际读取不能被旧快照代替。
                @contextmanager
                def synchronized_tx():
                    gate.wait(timeout=5)
                    with transaction() as db:
                        yield db
                runtime.store.tx = synchronized_tx
                try:
                    evolution.promote(cid)
                    outcomes.append("published")
                except ValueError:
                    outcomes.append("stale")
        workers = [threading.Thread(target=publish, args=(cid,)) for cid in ids]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertFalse(worker.is_alive())
        self.assertCountEqual(outcomes, ["published", "stale"])
        with MythRuntime(self.root) as runtime:
            self.assertEqual(len(SqliteEvolutionControl(runtime).history()), 1)

    # 评测矩阵计算后发生发布；晚到的证据提交不得把 PROMOTED 降回 ELIGIBLE/HOLD。
    def test_evidence_cannot_change_candidate_promoted_during_calculation(self):
        with MythRuntime(self.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            cid = "evidence-window"
            candidate = evolution.create_candidate(candidate_id=cid, config={"mode": "rule"}, changes=[cid])
            before, after = self._record_pair(runtime, cid, candidate["config"])
            evidence = {"baseline_eval_run_id": before["eval_run_id"], "candidate_eval_run_id": after["eval_run_id"]}
            evolution.attach_evaluation(cid, **evidence, min_pairs=2)

            # 固定计算与写回之间的交错；真实发布事务仍由生产代码执行。
            def publish_during_calibration(*args, **kwargs):
                evolution.promote(cid)
                return build_calibration_matrix(*args, **kwargs)
            with patch("myth.platform.evolution_store.build_calibration_matrix", side_effect=publish_during_calibration):
                with self.assertRaisesRegex(ValueError, "immutable"):
                    evolution.attach_evaluation(cid, **evidence, min_pairs=2)
            self.assertEqual(evolution.candidate(cid)["status"], "PROMOTED")


if __name__ == "__main__":
    unittest.main()
