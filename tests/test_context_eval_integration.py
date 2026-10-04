"""Context、Capability、Recovery、Evaluation 与 Acceptance 的固定回归。
这些测试验证吸收到现有模块后的合同；真实 Provider/长轨迹收益仍必须由固定 Eval 与实际运行证明。"""

from __future__ import annotations

import unittest

from myth.acceptance import (
    EvidenceKind,
    EvidenceQuote,
    SourceEvidence,
    source_digest,
    validate_source_evidence,
)
from myth.failures import (
    RecoveryAction,
    RecoveryBudget,
    RecoveryFailure,
    next_recovery_action,
)
from myth.platform.capabilities import capability_reachability, default_capabilities
from myth.platform.context import choose_context_mode, context_boundary
from myth.platform.evaluation import (
    EvalObservation,
    EvalReport,
    EvalVerdict,
    HarnessVariant,
    HeldOutEvalBoundary,
    attribution_matrix,
    capability_efficiency_gate,
    compare_observations,
    controlled_attribution,
    controlled_harness_variants,
)
from myth.platform.evolution import (
    ExperimentCandidate,
    ExperimentPhase,
    experiment_frontier,
)


# Context/Capability/Recovery 的 provider-visible 计价、滞回、可达性与恢复回归集合。
class ContextCapabilityRecoveryTests(unittest.TestCase):
    # 回归断言：只有实际 normal/compact provider-visible 投影差额进入节约量；没有稳定边界时不自动 Compact。
    def test_context_mode_requires_measured_compact_projection(self):
        decision = choose_context_mode(
            normal_bytes=32000,
            compact_bytes=None,
            max_bytes=42000,
            remaining_requests=4,
        )
        self.assertEqual(decision["mode"], "normal")
        self.assertEqual(decision["outcome"], "INELIGIBLE")
        self.assertEqual(decision["reason_code"], "no_settled_context_boundary")
        self.assertIsNone(decision["provider_visible_saving_bytes"])

    # 回归断言：高窗口压力下按真实投影节约进入 Compact，并显式保留未知 optimization debt。
    def test_context_mode_uses_provider_visible_saving(self):
        decision = choose_context_mode(
            normal_bytes=36000,
            compact_bytes=22000,
            max_bytes=42000,
            remaining_requests=3,
        )
        self.assertEqual(decision["mode"], "compact")
        self.assertEqual(decision["reason_code"], "context_pressure")
        self.assertEqual(decision["provider_visible_saving_bytes"], 14000)
        self.assertEqual(decision["projected_saving_bytes"], 42000)
        self.assertIsNone(decision["optimization_debt_bytes"])

    # 回归断言：进入 Compact 后使用较低退出阈值保持模式，避免在相邻步骤 normal/compact 来回振荡。
    def test_context_mode_hysteresis_holds_compact(self):
        decision = choose_context_mode(
            normal_bytes=28000,
            compact_bytes=18000,
            max_bytes=42000,
            remaining_requests=2,
            previous_mode="compact",
        )
        self.assertEqual(decision["mode"], "compact")
        self.assertEqual(decision["reason_code"], "hysteresis_hold")

    # 回归断言：已有同单位 upfront/debt 证据时，Context 必须看剩余 horizon 是否能回本。
    def test_context_economics_defers_until_debt_can_be_repaid(self):
        decision = choose_context_mode(
            normal_bytes=36000,
            compact_bytes=26000,
            max_bytes=42000,
            remaining_requests=2,
            upfront_cost_bytes=15000,
            outstanding_debt_bytes=10000,
        )
        self.assertEqual(decision["mode"], "normal")
        self.assertEqual(decision["reason_code"], "context_economics_not_repaid")
        self.assertEqual(decision["breakeven_requests"], 3)
        self.assertEqual(decision["projected_net_saving_bytes"], -5000)

    # 回归断言：窗口进入保护区时可越过经济回本门，避免为了省钱把 Context 撑爆。
    def test_context_pressure_can_override_unrepaid_debt_near_limit(self):
        decision = choose_context_mode(
            normal_bytes=39000,
            compact_bytes=26000,
            max_bytes=42000,
            remaining_requests=1,
            upfront_cost_bytes=20000,
            outstanding_debt_bytes=10000,
        )
        self.assertEqual(decision["mode"], "compact")
        self.assertEqual(decision["reason_code"], "context_pressure")
        self.assertLess(decision["projected_net_saving_bytes"], 0)

    # 回归断言：enabled 不等于 reachable；直接复用现有 Capability Registry，不建立第二套机制目录。
    def test_capability_reachability_uses_existing_registry(self):
        value = capability_reachability(
            default_capabilities(),
            "observation.read",
            enabled=True,
            exposed=False,
        )
        self.assertFalse(value.reachable)
        self.assertEqual(value.reason_code, "surface_not_exposed")

    # 回归断言：Compact 的语义边界只来自已结算 Artifact/Verification/Delegation，不从普通聊天文本猜进度。
    def test_context_boundaries_require_durable_settlement(self):
        self.assertEqual(
            context_boundary(
                {
                    "capability": "test.run",
                    "result": {"status": "PASSED", "evidence_ref": "test:x"},
                }
            ),
            "verification_settled",
        )
        self.assertEqual(
            context_boundary(
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
            context_boundary({"result": {"summary": "I think the task is done"}})
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


# Evaluation/Evolution 的能力下限、归因、held-out 与实验 lineage 固定回归集合。
class EvaluationEvolutionTests(unittest.TestCase):
    # 回归断言：候选先守 capability floor，再比较共同测量成本。
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
            report, report, (comparison,), require_improvement=True
        )
        self.assertTrue(ok, reason)
        self.assertEqual(aggregate["input_tokens"], -30.0)

    # 回归断言：逐题矩阵只提供 outcome flip/实际触发线索，不把相关性直接写成因果归因。
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

    # 回归断言：两机制实验只需四个唯一 Harness 变体；one-mechanism 与另一机制的 leave-one-out 复用同一次真实 Run。
    def test_controlled_harness_variant_plan_deduplicates_equivalent_ablations(self):
        variants = controlled_harness_variants(("compact", "recall"), prefix="exp")
        self.assertEqual(len(variants), 4)
        self.assertEqual(
            {frozenset(item.mechanisms) for item in variants},
            {
                frozenset(),
                frozenset({"compact"}),
                frozenset({"recall"}),
                frozenset({"compact", "recall"}),
            },
        )

    # 回归断言：真正的机制归因要求 full、one-mechanism 与 leave-one-out 同题对照；完整组合失败而去掉 compact 后恢复，标记受控负贡献。
    def test_controlled_attribution_requires_one_and_leave_one_out(self):
        variants = (
            HarnessVariant("base", ()),
            HarnessVariant("full", ("compact", "recall")),
            HarnessVariant("only-compact", ("compact",)),
            HarnessVariant("only-recall", ("recall",)),
        )
        observations = (
            EvalObservation(
                "case-1",
                EvalVerdict.PASS,
                "base",
                {"input_tokens": 100, "cache_write_input_tokens": 0},
                policy_id="p",
                harness_id="base",
            ),
            EvalObservation(
                "case-1",
                EvalVerdict.FAIL,
                "full",
                {"input_tokens": 70, "cache_write_input_tokens": 20},
                policy_id="p",
                harness_id="full",
            ),
            EvalObservation(
                "case-1",
                EvalVerdict.FAIL,
                "compact only",
                {"input_tokens": 80, "cache_write_input_tokens": 20},
                policy_id="p",
                harness_id="only-compact",
            ),
            EvalObservation(
                "case-1",
                EvalVerdict.PASS,
                "recall only",
                {"input_tokens": 100, "cache_write_input_tokens": 0},
                policy_id="p",
                harness_id="only-recall",
            ),
        )
        value = controlled_attribution(
            observations,
            variants,
            baseline_harness_id="base",
            full_harness_id="full",
        )
        compact = next(
            item for item in value["effects"] if item["mechanism"] == "compact"
        )
        recall = next(
            item for item in value["effects"] if item["mechanism"] == "recall"
        )
        self.assertTrue(compact["controlled"])
        self.assertEqual(compact["classification"], "supported_harm")
        self.assertEqual(compact["input_token_saving_per_request"], 30.0)
        self.assertEqual(compact["cache_write_debt_tokens"], 20.0)
        self.assertEqual(compact["breakeven_requests"], 1)
        self.assertTrue(recall["controlled"])
        self.assertEqual(recall["classification"], "mixed_or_interaction")

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


# 摘要/压缩候选绑定固定来源的验收回归集合。
class SourceEvidenceTests(unittest.TestCase):
    # 回归断言：逐字 quote 与 source digest 同时成立才能接受；流畅 summary 本身不产生可信度。
    def test_exact_quotes_bind_candidate_to_source(self):
        source = "FAILED tests/test_demo.py::test_x\nAssertionError: expected 2 got 3\n"
        candidate = SourceEvidence(
            source_ref="artifact:test-log",
            source_digest=source_digest(source),
            status="FAILED",
            evidence=(
                EvidenceQuote(
                    EvidenceKind.FAILURE,
                    "AssertionError: expected 2 got 3",
                ),
            ),
            summary="The test failed.",
        )
        verdict = validate_source_evidence(
            source, candidate, require_failure_evidence=True
        )
        self.assertTrue(verdict.accepted)

    # 回归断言：模型“顺手修正”一个字符也必须拒绝候选，调用方随后继续使用原始来源。
    def test_quote_drift_is_rejected(self):
        source = "Error Trace:\tthread 4830 panicked\n"
        candidate = SourceEvidence(
            source_ref="artifact:test-log",
            source_digest=source_digest(source),
            status="FAILED",
            evidence=(EvidenceQuote(EvidenceKind.FAILURE, "Error Trace: thread 4830 panicked"),),
        )
        verdict = validate_source_evidence(source, candidate)
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason_code, "unverifiable_quote")


if __name__ == "__main__":
    unittest.main()
