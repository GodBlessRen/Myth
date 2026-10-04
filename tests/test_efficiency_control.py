"""SoL-Pi 黄金机制落入 Myth 现有骨架后的纯合同回归。
这里只验证 Efficiency/Evidence 接口；真实 Provider/长轨迹收益仍必须由固定 Eval 与实际运行证明。"""

from __future__ import annotations

import unittest

from myth.platform.efficiency import (
    OptimizationEconomics,
    OptimizationOutcome,
    RecoveryAction,
    RecoveryBudget,
    RecoveryFailure,
    assess_reachability,
    decide_optimization,
    next_recovery_action,
    semantic_boundary,
)
from myth.platform.evaluation import (
    EvalObservation,
    EvalReport,
    EvalVerdict,
    HeldOutEvalBoundary,
    attribution_matrix,
    capability_efficiency_gate,
    compare_observations,
)
from myth.platform.evolution import (
    ExperimentCandidate,
    ExperimentPhase,
    experiment_frontier,
)
from myth.platform.evidence import (
    EvidenceKind,
    EvidenceQuote,
    EvidenceReceipt,
    evidence_digest,
    validate_evidence_receipt,
)


class EfficiencyControlTests(unittest.TestCase):
    # 回归断言：只有 provider-visible 的已测节约能进入回本计算，raw history 估算缺失时保持 DEFERRED。
    def test_economics_refuses_unmeasured_savings(self):
        decision = decide_optimization(
            OptimizationEconomics(
                "context_compaction",
                provider_visible_saving_per_request=None,
                upfront_cost=1000,
                remaining_requests=8,
            )
        )
        self.assertEqual(decision.outcome, OptimizationOutcome.DEFERRED)
        self.assertEqual(decision.reason_code, "measurement_unavailable")

    # 回归断言：upfront + outstanding debt 必须在剩余 horizon 内回本，不能因为“上下文很长”直接压缩。
    def test_economics_prices_debt_and_horizon(self):
        decision = decide_optimization(
            OptimizationEconomics(
                "context_compaction",
                provider_visible_saving_per_request=500,
                upfront_cost=1000,
                outstanding_debt=500,
                remaining_requests=4,
                requests_since_last_apply=3,
            )
        )
        self.assertEqual(decision.outcome, OptimizationOutcome.APPLIED)
        self.assertEqual(decision.breakeven_requests, 3)
        self.assertEqual(decision.projected_net_saving, 500)

    # 回归断言：自适应策略有 cooldown/hysteresis；安全保护可以显式越过普通经济门槛。
    def test_cooldown_and_emergency_override_are_distinct(self):
        cooled = decide_optimization(
            OptimizationEconomics(
                "context_compaction",
                1000,
                remaining_requests=10,
                requests_since_last_apply=1,
                cooldown_requests=2,
            )
        )
        self.assertEqual(cooled.reason_code, "cooldown_active")
        emergency = decide_optimization(
            OptimizationEconomics(
                "context_compaction",
                None,
                remaining_requests=None,
                requests_since_last_apply=0,
                emergency_required=True,
            )
        )
        self.assertEqual(emergency.outcome, OptimizationOutcome.APPLIED)
        self.assertEqual(emergency.reason_code, "emergency_override")

    # 回归断言：enabled 不等于 reachable；工具面没暴露时必须可解释地保持不可达。
    def test_reachability_separates_enabled_from_exposed(self):
        value = assess_reachability(
            "action_fusion", enabled=True, available=True, exposed=False
        )
        self.assertFalse(value.reachable)
        self.assertEqual(value.reason_code, "surface_not_exposed")

    # 回归断言：Compact 的语义边界只来自已结算 Artifact/Verification/Delegation，不从普通聊天文本猜进度。
    def test_semantic_boundaries_require_durable_settlement(self):
        self.assertEqual(
            semantic_boundary(
                {
                    "capability": "test.run",
                    "result": {"status": "PASSED", "evidence_ref": "test:x"},
                }
            ),
            "verification_settled",
        )
        self.assertEqual(
            semantic_boundary(
                {
                    "capability": "artifact.write",
                    "result": {
                        "artifact": {"digest": "abc"},
                        "evidence_ref": "artifact:x",
                    },
                }
            ),
            "artifact_settled",
        )
        self.assertIsNone(
            semantic_boundary({"result": {"summary": "I think the task is done"}})
        )

    # 回归断言：UNKNOWN 外部效果永远先 reconcile；表达层错误可在有界预算内走廉价修复。
    def test_recovery_ladder_keeps_unknown_and_representation_distinct(self):
        self.assertEqual(
            RecoveryAction.RECONCILE,
            next_recovery_action(RecoveryFailure.UNKNOWN, RecoveryBudget()),
        )
        self.assertEqual(
            RecoveryAction.REPAIR,
            next_recovery_action(RecoveryFailure.REPRESENTATION, RecoveryBudget()),
        )


class EvaluationEvolutionEfficiencyTests(unittest.TestCase):
    # 回归断言：候选只有在 capability floor 不退化且共同测量成本 Pareto 改善时才获得效率资格。
    def test_capability_floor_precedes_efficiency_gain(self):
        baseline_obs = EvalObservation(
            "case-1",
            EvalVerdict.PASS,
            "baseline",
            {"input_tokens": 100, "tool_calls": 3},
            policy_id="base",
            comparison_key="same",
        )
        candidate_obs = EvalObservation(
            "case-1",
            EvalVerdict.PASS,
            "candidate",
            {"input_tokens": 70, "tool_calls": 3},
            policy_id="candidate",
            comparison_key="same",
            mechanism_events=("observation_projection:APPLIED",),
        )
        comparison = compare_observations(baseline_obs, candidate_obs)
        report = EvalReport("suite", 1, 0, 0, 0)
        ok, reason, aggregate = capability_efficiency_gate(
            report, report, (comparison,)
        )
        self.assertTrue(ok, reason)
        self.assertEqual(aggregate["input_tokens"], -30.0)

    # 回归断言：逐题矩阵只提供 flip/机制线索，不把相关性直接写成因果归因。
    def test_attribution_matrix_keeps_causality_explicitly_false(self):
        value = attribution_matrix(
            (
                EvalObservation(
                    "case-1", EvalVerdict.PASS, "base", policy_id="a-base"
                ),
                EvalObservation(
                    "case-1",
                    EvalVerdict.FAIL,
                    "candidate",
                    policy_id="b-candidate",
                    mechanism_events=("context_compaction:APPLIED",),
                ),
            ),
            baseline_policy_id="a-base",
        )
        self.assertFalse(value["causal_attribution"])
        self.assertEqual(len(value["outcome_flips"]), 1)
        self.assertEqual(
            value["outcome_flips"][0]["candidate_mechanisms"],
            ["context_compaction:APPLIED"],
        )

    # 回归断言：held-out final case identity 不能进入 discovery feedback 集。
    def test_held_out_eval_boundary_rejects_overlap(self):
        boundary = HeldOutEvalBoundary(("search-1",), ("final-1",))
        self.assertTrue(boundary.may_feed_back("search-1"))
        self.assertFalse(boundary.may_feed_back("final-1"))
        with self.assertRaises(ValueError):
            HeldOutEvalBoundary(("same",), ("same",))

    # 回归断言：实验广度阶段按不同 hypothesis 保留，Harden 必须属于已有 lineage，workspace 固定 disposable。
    def test_disposable_experiment_frontier_separates_discover_and_harden(self):
        discover = ExperimentCandidate(
            "exp-a",
            "fold observations",
            ExperimentPhase.DISCOVER,
            ("observation_projection",),
        )
        duplicate = ExperimentCandidate(
            "exp-a2",
            "fold observations",
            ExperimentPhase.DISCOVER,
            ("observation_projection",),
        )
        harden = ExperimentCandidate(
            "exp-b",
            "harden exact recall",
            ExperimentPhase.HARDEN,
            ("exact_recall",),
            parent_experiment_id="exp-a",
            frozen_suite_ref="heldout-v1",
        )
        self.assertEqual(
            experiment_frontier((discover, duplicate, harden), phase=ExperimentPhase.DISCOVER),
            (discover,),
        )
        self.assertEqual(
            experiment_frontier((discover, harden), phase=ExperimentPhase.HARDEN),
            (harden,),
        )


class EvidenceBoundTransformationTests(unittest.TestCase):
    # 回归断言：逐字 quote 与 source digest 同时成立才能接受；流畅 summary 本身不产生可信度。
    def test_exact_quotes_bind_receipt_to_source(self):
        source = "FAILED tests/test_demo.py::test_x\nAssertionError: expected 2 got 3\n"
        receipt = EvidenceReceipt(
            source_ref="artifact:test-log",
            source_digest=evidence_digest(source),
            status="FAILED",
            evidence=(
                EvidenceQuote(
                    EvidenceKind.FAILURE,
                    "AssertionError: expected 2 got 3",
                ),
            ),
            summary="The test failed.",
        )
        verdict = validate_evidence_receipt(
            source, receipt, require_failure_evidence=True
        )
        self.assertTrue(verdict.accepted)

    # 回归断言：模型“顺手修正”一个字符也必须拒绝候选，调用方随后 fail-open 使用原始来源。
    def test_quote_drift_is_rejected(self):
        source = "Error Trace:\tthread 4830 panicked\n"
        receipt = EvidenceReceipt(
            source_ref="artifact:test-log",
            source_digest=evidence_digest(source),
            status="FAILED",
            evidence=(EvidenceQuote(EvidenceKind.FAILURE, "Error Trace: thread 4830 panicked"),),
        )
        verdict = validate_evidence_receipt(source, receipt)
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason_code, "unverifiable_quote")


if __name__ == "__main__":
    unittest.main()
