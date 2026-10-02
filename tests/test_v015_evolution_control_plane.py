from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.evaluation_runner import FoundationEvalRunner
from myth.platform.calibration import build_calibration_matrix
from myth.platform.cost_model import CostModel, SqliteCostModelRegistry
from myth.platform.evaluation import EvalObservation, EvalVerdict, compare_observations
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.platform.evolution_store import SqliteEvolutionControl
from myth.runtime import MythRuntime
from myth.workspace import Workspace


SETTINGS={
    "provider":"ollama",
    "model":"test",
    "ollama_url":"http://127.0.0.1:11434",
    "max_steps":6,
    "max_output_tokens":512,
    "thinking":False,
}


class EvolutionControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.suite=self.root/"release-suite.json"
        self.suite.write_text(json.dumps({
            "suite_id":"release-mini-v1",
            "version":1,
            "principle":"full fixed suite required for promotion",
            "cases":[
                {
                    "case_id":"intent-arithmetic-local",
                    "category":"intent",
                    "input":{"text":"计算 2+3*4"},
                    "expected":{"route":"deterministic","answer":"14","model_calls":0},
                },
                {
                    "case_id":"resolution-agent-l0",
                    "category":"information_resolution",
                    "input":{"text":"帮我分析一个新的产品方案。"},
                    "expected":{"route":"agent","resolution":"L0"},
                },
            ],
        },ensure_ascii=False),encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _record_pair(self,runtime,candidate_id,config):
        evolution=SqliteEvolutionControl(runtime)
        baseline=evolution.policy(evolution.candidate(candidate_id)["baseline_policy_id"])
        baseline_result=FoundationEvalRunner.from_path(
            self.suite,
            policy_id=baseline["policy_id"],
            policy_config=baseline["config"],
        ).run()
        candidate_result=FoundationEvalRunner.from_path(
            self.suite,
            policy_id=candidate_id,
            policy_config=config,
        ).run()
        ledger=SqliteEvaluationLedger(runtime)
        before=ledger.record(baseline_result,policy_id=baseline["policy_id"])
        after=ledger.record(candidate_result,policy_id=candidate_id)
        return before,after

    def test_cost_model_is_versioned_immutable_and_matrix_keeps_case_facts(self):
        with MythRuntime(self.root) as runtime:
            registry=SqliteCostModelRegistry(runtime)
            model=CostModel(
                "context-cost-v1",1,
                {"context_chars":0.001,"tool_calls":2.0},
                "explicit test weights",
            )
            registry.put(model)
            self.assertEqual(registry.get("context-cost-v1")["version"],1)
            with self.assertRaises(ValueError):
                registry.put(CostModel("context-cost-v1",2,{"context_chars":0.1},"changed"))

        before=EvalObservation(
            "case",EvalVerdict.FAIL,"before",
            {"context_chars":500,"tool_calls":0},
            policy_id="a",comparison_key="case",
        )
        after=EvalObservation(
            "case",EvalVerdict.PASS,"after",
            {"context_chars":1500,"tool_calls":1},
            policy_id="b",comparison_key="case",
        )
        matrix=build_calibration_matrix(
            [compare_observations(before,after)],
            CostModel("context-cost-v1",1,{"context_chars":0.001,"tool_calls":2.0}),
        )
        self.assertEqual(matrix.positive_pairs,1)
        self.assertEqual(matrix.negative_pairs,0)
        self.assertEqual(matrix.total_weighted_cost,3.0)
        self.assertAlmostEqual(matrix.gain_per_cost,1/3)
        self.assertTrue(matrix.promotion_gate(min_pairs=1)[0])

    def test_partial_suite_cannot_be_used_as_promotion_evidence(self):
        with MythRuntime(self.root) as runtime:
            evolution=SqliteEvolutionControl(runtime)
            candidate=evolution.create_candidate(
                candidate_id="policy-partial",
                config={"mode":"rule"},
                changes=["candidate exists only to test completeness gate"],
            )
            baseline=evolution.policy(candidate["baseline_policy_id"])
            base_result=FoundationEvalRunner.from_path(
                self.suite,
                policy_id=baseline["policy_id"],
                policy_config=baseline["config"],
            ).run(["intent-arithmetic-local"])
            candidate_result=FoundationEvalRunner.from_path(
                self.suite,
                policy_id=candidate["candidate_id"],
                policy_config=candidate["config"],
            ).run(["intent-arithmetic-local"])
            ledger=SqliteEvaluationLedger(runtime)
            before=ledger.record(base_result,policy_id=baseline["policy_id"])
            after=ledger.record(candidate_result,policy_id=candidate["candidate_id"])
            self.assertFalse(before["complete_suite"])
            with self.assertRaises(ValueError):
                evolution.attach_evaluation(
                    candidate["candidate_id"],
                    baseline_eval_run_id=before["eval_run_id"],
                    candidate_eval_run_id=after["eval_run_id"],
                )

    def test_candidate_promote_freezes_future_turn_policy_and_rollback(self):
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            workspace.repository.save_settings(SETTINGS)
            sid=workspace.repository.create_session()["id"]
            first=workspace.repository.create_turn(
                sid,"第一个请求","v015-before-promote"
            )
            first_snapshot=workspace.repository.turn(first["run_id"])["snapshot"]
            self.assertEqual(
                first_snapshot["policy_bindings"]["information_resolution"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            workspace.repository.block(first["run_id"],"FAILED","test closes first turn")

            evolution=SqliteEvolutionControl(runtime)
            candidate=evolution.create_candidate(
                candidate_id="policy-rule-v2",
                config={"mode":"rule"},
                changes=["version the same rule policy through the release control plane"],
            )
            before,after=self._record_pair(runtime,candidate["candidate_id"],candidate["config"])
            evaluated=evolution.attach_evaluation(
                candidate["candidate_id"],
                baseline_eval_run_id=before["eval_run_id"],
                candidate_eval_run_id=after["eval_run_id"],
                min_pairs=2,
            )
            self.assertEqual(evaluated["status"],"ELIGIBLE")
            self.assertEqual(evaluated["calibration"]["negative_pairs"],0)
            promoted=evolution.promote(candidate["candidate_id"])
            self.assertEqual(promoted["active"]["policy_id"],candidate["candidate_id"])
            self.assertEqual(promoted["active"]["revision"],2)

            # A new composition/admission sees the promoted pointer.
            workspace2=Workspace(runtime)
            second=workspace2.repository.create_turn(
                sid,"第二个请求","v015-after-promote"
            )
            second_snapshot=workspace2.repository.turn(second["run_id"])["snapshot"]
            self.assertEqual(
                second_snapshot["policy_bindings"]["information_resolution"],
                candidate["candidate_id"],
            )
            # Existing durable Turn evidence did not change.
            self.assertEqual(
                workspace.repository.turn(first["run_id"])["snapshot"]["policy_bindings"]["information_resolution"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            workspace2.repository.block(second["run_id"],"FAILED","test closes second turn")

            rolled=evolution.rollback(reason="test rollback")
            self.assertEqual(
                rolled["active"]["policy_id"],
                SqliteEvolutionControl.BUILTIN_RESOLUTION_POLICY,
            )
            self.assertEqual(rolled["active"]["revision"],3)
            self.assertEqual(rolled["history"][0]["action"],"ROLLBACK")

    def test_stale_candidate_cannot_overwrite_new_active_policy(self):
        with MythRuntime(self.root) as runtime:
            evolution=SqliteEvolutionControl(runtime)
            one=evolution.create_candidate(
                candidate_id="policy-one",config={"mode":"rule"},changes=["one"]
            )
            two=evolution.create_candidate(
                candidate_id="policy-two",config={"mode":"rule"},changes=["two"]
            )
            for candidate in (one,two):
                before,after=self._record_pair(runtime,candidate["candidate_id"],candidate["config"])
                evolution.attach_evaluation(
                    candidate["candidate_id"],
                    baseline_eval_run_id=before["eval_run_id"],
                    candidate_eval_run_id=after["eval_run_id"],
                    min_pairs=2,
                )
            evolution.promote(one["candidate_id"])
            with self.assertRaises(ValueError):
                evolution.promote(two["candidate_id"])


if __name__=="__main__":
    unittest.main()
