"""Goodfire 式反例优先评测：固定四臂因子结果，不调用 Provider。"""

import unittest

from myth.task_benchmark import CONTEXT_BENCHMARK_ARMS, summarize_context_ablation


class ContextFalsificationTests(unittest.TestCase):
    """只承认独立 Oracle、冻结配置与真实四臂试次；不把差异自动当成因果。"""

    def trials(self, outcomes, *, repeats=1, missing_oracle=False):
        rows = []
        for repeat in range(1, repeats + 1):
            for arm in CONTEXT_BENCHMARK_ARMS:
                rows.append({
                    "case_id": "fixed-case",
                    "repeat": repeat,
                    "arm": arm,
                    "success": None if missing_oracle and arm == "context-full" else outcomes[arm],
                    "status": "COMPLETED",
                    "model_calls": 1,
                    "human_takeover": False,
                    "repeated_tool_calls": 0,
                    "usage_measured": {"input_tokens": {
                        "context-baseline": 100, "context-causal": 80,
                        "context-relevance": 90, "context-full": 95,
                    }[arm], "output_tokens": 10, "provider_wall_ms": 10},
                    "context_activation": [{
                        "causality": "causal-active-set-v2"
                        if arm in ("context-causal", "context-full")
                        else "disabled-for-controlled-evaluation",
                        "relevance": "cross-source-bounded-lexical-candidate-ranking"
                        if arm in ("context-relevance", "context-full")
                        else "disabled-for-controlled-evaluation",
                    }],
                })
        return rows

    def summary(self, rows, repeats=1):
        return summarize_context_ablation(
            rows, tuple(CONTEXT_BENCHMARK_ARMS), ("fixed-case",), repeats,
            kind="harness_fixture", complete_suite=True,
        )

    def test_quality_interaction_and_counterexample_not_promotion(self):
        rows = self.trials({
            "context-baseline": True, "context-causal": False,
            "context-relevance": True, "context-full": True,
        })
        result = self.summary(rows)
        probe = result["pairs"][0]["falsification"]
        self.assertEqual(probe["status"], "OBSERVED_FACTORIAL")
        self.assertEqual(probe["quality_interaction"], 1)
        self.assertEqual(probe["quality_contrasts"]["causal_without_relevance"], -1)
        self.assertIn("causal_without_relevance", probe["counterexamples_to_nonregression"])
        self.assertEqual(probe["cost_interactions"]["input_tokens"], 25.0)
        self.assertEqual(result["falsification"]["counterexample_case_count"], 1)
        self.assertFalse(result["falsification"]["causal_attribution"])
        self.assertIsNone(probe["material_intervention_verified"])
        self.assertFalse(result["promotion_eligible"])

    def test_repeats_do_not_fake_independent_cases(self):
        rows = self.trials({
            "context-baseline": True, "context-causal": False,
            "context-relevance": True, "context-full": True,
        }, repeats=3)
        result = self.summary(rows, repeats=3)
        self.assertEqual(result["falsification"]["counterexample_trial_count"], 3)
        self.assertEqual(result["falsification"]["counterexample_case_count"], 1)

    def test_unknown_oracle_does_not_become_measured_failure(self):
        rows = self.trials({arm: True for arm in CONTEXT_BENCHMARK_ARMS},
                           missing_oracle=True)
        probe = self.summary(rows)["pairs"][0]["falsification"]
        self.assertEqual(probe["status"], "UNVERIFIED")
        self.assertEqual(probe["reason"], "missing_independent_oracle")

    def test_duplicate_arm_blocks_disqualify_probe(self):
        rows = self.trials({arm: True for arm in CONTEXT_BENCHMARK_ARMS})
        result = self.summary(rows + [dict(rows[0])])
        self.assertEqual(result["pairs"][0]["falsification"]["status"], "UNVERIFIED")
        self.assertEqual(result["pairs"][0]["falsification"]["reason"], "duplicate_trial_block")

    def test_no_quality_difference_is_not_evidence_of_benefit(self):
        rows = self.trials({arm: True for arm in CONTEXT_BENCHMARK_ARMS})
        result = self.summary(rows)
        self.assertTrue(result["pairs"][0]["falsification"]["no_observed_quality_difference"])
        self.assertEqual(result["falsification"]["no_quality_difference_blocks"], 1)
        self.assertFalse(result["falsification"]["causal_attribution"])
