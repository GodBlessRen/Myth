"""FRAMEBREAKER 证据门禁回归：合成四臂数据只测试纯判定逻辑，不冒充真实 Provider 运行。"""

import unittest

from myth.task_benchmark import CONTEXT_BENCHMARK_ARMS, summarize_context_ablation


class ContextReleaseEvidenceGateTests(unittest.TestCase):
    """所有四臂的 Oracle 和模型调用证据必须齐备，才允许提出 Held-out 复核建议。"""

    # 八个独立 Case × 三个 Repeat × 四个 Arm；主成本指标全部下降，构造本应可复核的正控。
    @staticmethod
    def _rows():
        rows = []
        for case in range(8):
            for repeat in range(1, 4):
                for arm in CONTEXT_BENCHMARK_ARMS:
                    causal = arm in {"context-causal", "context-full"}
                    relevance = arm in {"context-relevance", "context-full"}
                    rows.append({
                        "case_id": f"case-{case}",
                        "repeat": repeat,
                        "arm": arm,
                        "status": "COMPLETED",
                        "success": True,
                        "model_calls": 1,
                        "human_takeover": False,
                        "repeated_tool_calls": 0,
                        "usage_measured": {
                            "input_tokens": {
                                "context-baseline": 120,
                                "context-causal": 90,
                                "context-relevance": 105,
                                "context-full": 100,
                            }[arm],
                            "output_tokens": 10,
                            "provider_wall_ms": 10,
                        },
                        "context_activation": [{
                            "causality": (
                                "causal-active-set-v2"
                                if causal else "disabled-for-controlled-evaluation"
                            ),
                            "relevance": (
                                "cross-source-bounded-lexical-candidate-ranking"
                                if relevance else "disabled-for-controlled-evaluation"
                            ),
                        }],
                    })
        return rows

    # 传入 real_provider 只用于触发纯门禁条件；该合成数据不能作为真实 Provider 收据。
    @staticmethod
    def _summary(rows):
        return summarize_context_ablation(
            rows,
            tuple(CONTEXT_BENCHMARK_ARMS),
            tuple(f"case-{case}" for case in range(8)),
            3,
            kind="real_provider",
            complete_suite=True,
        )

    # 正控必须保持可进入复核，避免以全面关门替代针对性证据修复。
    def test_complete_oracles_and_calls_retain_readiness(self):
        result = self._summary(self._rows())
        self.assertEqual(result["falsification"]["unverified_blocks"], 0)
        self.assertTrue(result["paired_significance"]["passed"])
        self.assertTrue(result["ready_for_separate_heldout_review"])
        self.assertFalse(result["promotion_eligible"])

    # 即便 Baseline/Full 与成本统计都良好，任一中间 Arm 缺 Oracle 也不能放行。
    def test_missing_intermediate_oracle_blocks_readiness(self):
        rows = self._rows()
        for row in rows:
            if (row["case_id"], row["repeat"], row["arm"]) == (
                "case-0", 1, "context-causal"
            ):
                row["success"] = None
        result = self._summary(rows)
        self.assertEqual(result["falsification"]["unverified_blocks"], 1)
        self.assertFalse(result["ready_for_separate_heldout_review"])

    # 一个 Arm 实际未调用模型时，不得借其余三个 Arm 的计量充当完整干预证据。
    def test_unexercised_variant_blocks_readiness(self):
        rows = self._rows()
        for row in rows:
            if (row["case_id"], row["repeat"], row["arm"]) == (
                "case-0", 1, "context-relevance"
            ):
                row["model_calls"] = 0
                row["context_activation"] = []
        result = self._summary(rows)
        self.assertFalse(result["ready_for_separate_heldout_review"])


if __name__ == "__main__":
    unittest.main()
