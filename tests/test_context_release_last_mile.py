"""The Last Mile：重复试次统计、固定 Suite 证据和双阶段只读复核。

全部“真实 Provider”标签均为离线合成输入；测试只证明逻辑与拒绝条件，
不证明任何外部模型已被调用、模型权重真实固定或任务获得了统计独立性。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.context_release_review import review_context_release
from myth.domain import digest_json
from myth.platform.trial_statistics import case_clustered_sign_test
from myth.task_benchmark import CONTEXT_BENCHMARK_ARMS, summarize_context_ablation


class ContextReleaseLastMileTests(unittest.TestCase):
    """使用显式临时目录和合成试次，检验双阶段报告能拒绝不完整/伪统计结论。"""

    # 每个测试有唯一临时证据目录；模拟器不访问模型/网络。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    # 关闭本例目录资源；不影响其他测试或正式项目状态。
    def tearDown(self):
        self.tmp.cleanup()

    # 用 case×repeat×arm 原子格构造一致的合成报告，刻意固定所有环境身份。
    def bundle(self, name, partition, *, prefix=None, case_count=7, repeats=3,
               model_digest="ollama-test-pin", source_digest="a" * 64):
        root = self.root / name
        root.mkdir()
        identity = prefix or name
        ids = [f"{identity}-{index}" for index in range(case_count)]
        suite = {
            "suite_id": f"{name}-v1", "partition": partition,
            "cases": [{"id": case_id, "category": "fixed", "acceptance": {}}
                      for case_id in ids],
        }
        arms = tuple(CONTEXT_BENCHMARK_ARMS)
        trials = []
        for repeat in range(1, repeats + 1):
            for case_id in ids:
                for arm in arms:
                    evidence = root / f"{repeat}-{case_id}-{arm}" / ".runtime"
                    evidence.mkdir(parents=True)
                    trials.append({
                        "case_id": case_id, "repeat": repeat, "arm": arm,
                        "success": True, "status": "COMPLETED", "model_calls": 1,
                        "human_takeover": False, "repeated_tool_calls": 0,
                        "run_ids": [f"{repeat}-{case_id}-{arm}"],
                        "evidence_root": str(evidence),
                        "context_activation": [{
                            "causality": (
                                "causal-active-set-v2"
                                if arm in {"context-causal", "context-full"}
                                else "disabled-for-controlled-evaluation"
                            ),
                            "relevance": (
                                "cross-source-bounded-lexical-candidate-ranking"
                                if arm in {"context-relevance", "context-full"}
                                else "disabled-for-controlled-evaluation"
                            ),
                        }],
                        "usage_measured": {
                            "input_tokens": 100 if arm == "context-full" else 150,
                            "output_tokens": 20,
                            "provider_wall_ms": 300 if arm == "context-full" else 400,
                        },
                    })
        report = {
            "suite_id": suite["suite_id"],
            "suite_digest": digest_json(suite),
            "source_digest": source_digest,
            "runtime_version": "0.27.0",
            "provider": "ollama", "model": "test-model:exact",
            "model_metadata": {"digest": model_digest} if model_digest else None,
            "settings": {"temperature": 0.0, "thinking": False},
            "repeats": repeats, "arms": list(arms), "kind": "real_provider",
            "partition": "declared_heldout" if partition == "heldout" else "discovery",
            "suite_case_count": len(ids), "selected_case_count": len(ids),
            "complete_suite": True,
            "planned_trials": len(trials),
            "trials": trials,
        }
        report["context_ablation"] = summarize_context_ablation(
            trials, arms, tuple(ids), repeats, kind="real_provider", complete_suite=True,
        )
        (root / "suite.json").write_text(
            json.dumps(suite, ensure_ascii=False), encoding="utf-8",
        )
        self.save_report(root, report)
        return root

    # 模拟原子保存后的报告版本；复核时会逐字段重新核算。
    def save_report(self, root, report):
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8",
        )

    # 三次重跑同 Case 只贡献一次统计符号，不能凭重跑次数夸大独立样本。
    def test_repeated_one_case_is_not_statistical_evidence(self):
        pairs = [
            {"case_id": "only", "repeat": index, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -4}}}
            for index in range(1, 11)
        ]
        result = case_clustered_sign_test(pairs, ("only",), 10)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["discordant_cases"], 1)
        self.assertEqual(result["p_one_sided"], 0.5)
        self.assertFalse(result["passed"])

    # 六个真正不同的 Case 全部改善且有三次重复时单侧精确 p=1/64。
    def test_six_distinct_cases_have_an_exact_one_sided_p_value(self):
        cases = tuple(f"case-{i}" for i in range(6))
        pairs = [
            {"case_id": case_id, "repeat": repeat, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -1}}}
            for case_id in cases for repeat in range(1, 4)
        ]
        result = case_clustered_sign_test(pairs, cases, 3)
        self.assertTrue(result["passed"])
        self.assertEqual(result["discordant_cases"], 6)
        self.assertEqual(result["p_one_sided"], 1 / 64)
        self.assertEqual(len(result["case_cost_deltas"]), 6)

    # 相同 Case/Repeat 的重复上报或缺测成本都使完整分母失败。
    def test_duplicate_or_missing_paired_samples_fail_closed(self):
        cases = tuple(f"case-{i}" for i in range(7))
        pairs = [
            {"case_id": case_id, "repeat": repeat, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -1}}}
            for case_id in cases for repeat in range(1, 4)
        ]
        duplicate = case_clustered_sign_test(pairs + [pairs[0]], cases, 3)
        self.assertFalse(duplicate["passed"])
        self.assertTrue(duplicate["invalid_pairs"])
        missing = case_clustered_sign_test(pairs[:-1], cases, 3)
        self.assertFalse(missing["passed"])
        self.assertEqual(len(missing["missing_pairs"]), 1)

    # 两个真实模型报告形状可以进入人工复核，但合成测试绝不授予生产发布许可。
    def test_discovery_and_heldout_recompute_to_manual_review(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["heldout"]["paired_significance"]["p_one_sided"], 1 / 128)
        self.assertTrue(result["evidence_digest"].startswith("sha256:"))

    # 改动 Trial 后不更新汇总不可掩盖：复核用原始格子重新计算后拒绝不一致。
    def test_report_summary_tampering_is_rejected(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        raw = json.loads((final / "report.json").read_text(encoding="utf-8"))
        raw["trials"][0]["success"] = False
        self.save_report(final, raw)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            review_context_release(discovery, final)

    # Discovery/heldout 即使有两个 Suite 名称，同题身份重叠也不能自称独立验证。
    def test_case_overlap_returns_hold(self):
        discovery = self.bundle("discovery", "discovery", prefix="same")
        final = self.bundle("heldout", "heldout", prefix="same")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("overlap" in reason for reason in result["reasons"]))

    # 真实模型版本必须一致且可核对；名称相同而权重 digest 缺失/变化时停止晋升。
    def test_model_digest_missing_or_changed_returns_hold(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout", model_digest="other-digest")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("model weight digest" in reason for reason in result["reasons"]))

    # 完整证据必须能在本地回读，不能把缺失 .runtime 的摘要冒充收据原件。
    def test_missing_evidence_directory_is_rejected(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        raw = json.loads((final / "report.json").read_text(encoding="utf-8"))
        missing = Path(raw["trials"][0]["evidence_root"])
        missing.rmdir()
        with self.assertRaisesRegex(ValueError, "durable evidence is missing"):
            review_context_release(discovery, final)

    # 单次测试即使所有成本下降也不具备对照统计效力。
    def test_single_repeat_report_is_rejected(self):
        discovery = self.bundle("discovery", "discovery", repeats=1)
        final = self.bundle("heldout", "heldout")
        with self.assertRaisesRegex(ValueError, "repeated trials"):
            review_context_release(discovery, final)


if __name__ == "__main__":
    unittest.main()
