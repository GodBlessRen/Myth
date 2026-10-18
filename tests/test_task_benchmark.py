"""回归边界：固定任务 Harness 及独立验收。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

import json
from pathlib import Path
import tempfile
import unittest

from myth.task_benchmark import (
    CONTEXT_BENCHMARK_ARMS, run_task_benchmark, summarize_context_ablation,
)


SUITE = Path(__file__).resolve().parents[1] / "evals" / "daily-v1.json"


# 固定任务 Harness 及独立验收的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class TaskBenchmarkTests(unittest.TestCase):
    # 回归断言：固定题完整重复、两条路径均留数据库和独立验收；替身只验证 Harness。
    def test_complete_fixed_suite_repeats_and_persists_both_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            report = run_task_benchmark(SUITE, output, repeats=3)
            self.assertTrue(report["complete_suite"])
            self.assertEqual(report["kind"], "harness_fixture")
            self.assertEqual(len(report["trials"]), 60)
            self.assertTrue(all(t["success"] for t in report["trials"]))
            self.assertEqual(report["summary"]["myth"]["passed"], 30)
            self.assertEqual(
                json.loads((output / "report.json").read_text(encoding="utf-8"))[
                    "suite_digest"
                ],
                report["suite_digest"],
            )
            self.assertTrue(
                all(Path(t["evidence_root"]).is_dir() for t in report["trials"])
            )
            with self.assertRaises(FileExistsError):
                run_task_benchmark(SUITE, output)

    # 回归断言：筛题报告明确 partial，不能自称完整基线。
    def test_filtered_run_never_claims_complete_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_task_benchmark(
                SUITE, Path(tmp) / "filtered", repeats=1, case_ids=["arithmetic"]
            )
            self.assertFalse(report["complete_suite"])
            self.assertEqual(len(report["trials"]), 2)
            self.assertEqual(report["trials"][0]["model_calls"], 0)
            self.assertEqual(report["trials"][1]["model_calls"], 1)

    # 回归断言：重复试次区分“至少成功一次”的 capability 与“每次都成功”的 reliability，并报告 95% 区间。
    def test_summary_reports_pass_at_k_and_pass_pow_k(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_task_benchmark(SUITE, Path(tmp) / "evidence", repeats=3)
            summary = report["summary"]["myth"]
            self.assertEqual(summary["k"], 3)
            self.assertEqual(summary["complete_case_count"], 10)
            self.assertEqual(summary["pass_at_k"], 1.0)
            self.assertEqual(summary["pass_pow_k"], 1.0)
            self.assertEqual(summary["mixed_outcome_cases"], [])
            self.assertEqual(summary["all_failed_cases"], [])
            self.assertEqual(len(summary["pass_at_k_ci95"]), 2)
            self.assertEqual(len(summary["pass_pow_k_ci95"]), 2)
            self.assertIsNotNone(summary["model_calls_per_success"])
            self.assertGreater(summary["model_calls_per_success"], 0)

    # 回归断言：筛题仍按固定重复次数计算可靠性；只有跑满 k 次的 case 才进入 pass@k/pass^k 分母。
    def test_filtered_repeats_keep_reliability_denominator_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_task_benchmark(
                SUITE, Path(tmp) / "filtered-reliability", repeats=3,
                case_ids=["arithmetic"], arms=("myth",)
            )
            summary = report["summary"]["myth"]
            self.assertEqual(summary["complete_case_count"], 1)
            self.assertEqual(summary["incomplete_cases"], [])
            self.assertEqual(summary["pass_at_k"], 1.0)
            self.assertEqual(summary["pass_pow_k"], 1.0)

    # 回归断言：错误模型 claim 以真实对象字节判失败，而非按回答措辞算成功。
    def test_wrong_completion_is_counted_by_artifact_bytes_not_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = json.loads(SUITE.read_text(encoding="utf-8"))
            case = next(c for c in suite["cases"] if c["id"] == "artifact-text")
            case["steps"][0]["args"]["content"] = "WRONG"
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(suite), encoding="utf-8")
            report = run_task_benchmark(
                path, Path(tmp) / "bad", repeats=1, case_ids=["artifact-text"]
            )
            self.assertTrue(all(t["status"] == "COMPLETED" for t in report["trials"]))
            self.assertTrue(
                all(t["completion_without_acceptance"] for t in report["trials"])
            )
            self.assertFalse(any(t["success"] for t in report["trials"]))

    # 同题四组使用真正冻结的 Evaluation override；不是对同一模型回答修改标签。
    def test_controlled_context_four_way_persists_real_model_requests(self):
        """Scripted 只证明 Harness 接通；每个 Turn 都存下本次组态和真实 Context 报告。"""
        with tempfile.TemporaryDirectory() as tmp:
            arms = tuple(CONTEXT_BENCHMARK_ARMS)
            out = Path(tmp) / "four-way"
            report = run_task_benchmark(
                SUITE, out, repeats=1, arms=arms,
                case_ids=["source-read", "knowledge-fact"],
            )
            self.assertFalse(report["complete_suite"])
            self.assertEqual(report["kind"], "harness_fixture")
            self.assertEqual(len(report["trials"]), 8)
            self.assertTrue(all(t["success"] for t in report["trials"]))
            ablation = report["context_ablation"]
            self.assertEqual(ablation["complete_pair_count"], 2)
            self.assertEqual(ablation["quality"]["both_pass"], 2)
            self.assertFalse(ablation["ready_for_separate_heldout_review"])
            self.assertFalse(ablation["promotion_eligible"])
            self.assertEqual(ablation["cost"]["input_tokens"]["paired_samples"], 2)
            self.assertIsNone(ablation["cost"]["input_tokens"]["delta"])
            self.assertEqual(ablation["activation_mismatch_count"], 0)
            for trial in report["trials"]:
                self.assertEqual(trial["harness_mechanisms"], list(CONTEXT_BENCHMARK_ARMS[trial["arm"]]))
                self.assertEqual(trial["usage_samples"]["input_tokens"], trial["model_calls"])
                self.assertGreater(trial["serialized_request_bytes"], 0)
                self.assertTrue(all(
                    record["causality"] == (
                        "causal-active-set-v2"
                        if "context_causal_guard" in CONTEXT_BENCHMARK_ARMS[trial["arm"]]
                        else "disabled-for-controlled-evaluation"
                    )
                    for record in trial["context_activation"]
                ))
                self.assertTrue(all(
                    record["relevance"] == (
                        "cross-source-bounded-lexical-candidate-ranking"
                        if "context_relevance_ranking" in CONTEXT_BENCHMARK_ARMS[trial["arm"]]
                        else "disabled-for-controlled-evaluation"
                    )
                    for record in trial["context_activation"]
                ))
            self.assertEqual(
                json.loads((out / "report.json").read_text(encoding="utf-8"))["context_ablation"]["complete_pair_count"],
                2,
            )

    # 与 Discovery 不同的标记集具有独立验收合同；公开 heldout 只是一种声明，不可冒充真正盲测。
    def test_declared_heldout_fixture_has_separate_suite_and_oracles(self):
        """全量七题四组以零外部模型调用走真实 Workspace/Ticket/独立 oracle。"""
        heldout = SUITE.with_name("context-heldout-v1.json")
        with tempfile.TemporaryDirectory() as tmp:
            report = run_task_benchmark(
                heldout, Path(tmp) / "heldout", repeats=1,
                arms=tuple(CONTEXT_BENCHMARK_ARMS),
            )
            self.assertTrue(report["complete_suite"])
            self.assertEqual(report["partition"], "declared_heldout")
            self.assertEqual(report["selected_case_count"], 7)
            self.assertEqual(report["context_ablation"]["complete_pair_count"], 7)
            self.assertTrue(all(t["success"] for t in report["trials"]))
            self.assertEqual(report["kind"], "harness_fixture")
            self.assertFalse(report["context_ablation"]["ready_for_separate_heldout_review"])

    # 即使实测部分成本优于 baseline，任一缺测或安全退化也不能升级成效率 winner。
    def test_pairwise_missing_token_and_unknown_are_not_promotion_evidence(self):
        """对受控质量翻转与缺测的计算保留真实分母，不补 0 Token 或安全成功。"""
        trials = []
        for arm in CONTEXT_BENCHMARK_ARMS:
            t = {
                "case_id": "sensitive", "repeat": 1, "arm": arm,
                "success": arm != "context-full",
                "status": "UNKNOWN" if arm == "context-full" else "COMPLETED",
                "human_takeover": arm == "context-full",
                "repeated_tool_calls": 1 if arm == "context-full" else 0,
                "context_activation": [{
                    "causality": "disabled-for-controlled-evaluation"
                    if arm not in ("context-causal", "context-full") else "causal-active-set-v2",
                    "relevance": "disabled-for-controlled-evaluation"
                    if arm not in ("context-relevance", "context-full")
                    else "cross-source-bounded-lexical-candidate-ranking",
                }],
                "usage_measured": {
                    "input_tokens": None if arm == "context-full" else 30,
                    "output_tokens": 20, "provider_wall_ms": 150,
                },
            }
            trials.append(t)
        summary = summarize_context_ablation(
            trials, tuple(CONTEXT_BENCHMARK_ARMS), ("sensitive",), 1,
            kind="real_provider", complete_suite=True,
        )
        self.assertEqual(summary["quality"]["regressed"], 1)
        self.assertEqual(summary["safety"]["new_unknown"], 1)
        self.assertEqual(summary["safety"]["new_human_takeover"], 1)
        self.assertEqual(summary["safety"]["more_repeated_tool_calls"], 1)
        self.assertIsNone(summary["cost"]["input_tokens"]["delta"])
        self.assertFalse(summary["ready_for_separate_heldout_review"])
        self.assertFalse(summary["promotion_eligible"])

    # 模拟两种受控证据覆盖，证明 winner 预检真正验证所有四组，而不是只检查 baseline/full。
    def test_real_provider_readiness_requires_all_four_arm_receipts(self):
        """离线构造的数字仅测试发布门禁逻辑，不构成真实 Provider 领先证据。"""
        records = []
        for arm in CONTEXT_BENCHMARK_ARMS:
            records.append({
                "case_id": "edge", "repeat": 1, "arm": arm,
                "status": "COMPLETED", "model_calls": 1,
                "success": arm != "context-baseline",
                "human_takeover": False, "repeated_tool_calls": 0,
                "usage_measured": {
                    "input_tokens": 50 if arm == "context-full" else 60,
                    "output_tokens": 10, "provider_wall_ms": 100,
                },
                "context_activation": [{
                    "causality": "causal-active-set-v2" if arm in (
                        "context-causal", "context-full"
                    ) else "disabled-for-controlled-evaluation",
                    "relevance": "cross-source-bounded-lexical-candidate-ranking"
                    if arm in ("context-relevance", "context-full")
                    else "disabled-for-controlled-evaluation",
                }],
            })
        summary = summarize_context_ablation(
            records, tuple(CONTEXT_BENCHMARK_ARMS), ("edge",), 1,
            kind="real_provider", complete_suite=True,
        )
        self.assertTrue(summary["ready_for_separate_heldout_review"])
        self.assertFalse(summary["promotion_eligible"])
        self.assertEqual(summary["fully_measured_variant_pairs"], 1)
        records[1] = {**records[1], "status": "RUNNER_ERROR", "model_calls": None,
                      "usage_measured": {}}
        rejected = summarize_context_ablation(
            records, tuple(CONTEXT_BENCHMARK_ARMS), ("edge",), 1,
            kind="real_provider", complete_suite=True,
        )
        self.assertFalse(rejected["ready_for_separate_heldout_review"])
        self.assertEqual(rejected["fully_measured_variant_pairs"], 0)

    # 不完整对照不可以当作全四机制，基线和路由组混用应在创建证据目录前拒绝。
    def test_context_ablation_rejects_mixed_arms_and_marks_incomplete(self):
        """两臂诊断只能产生 INCOMPLETE 配对，绝不能自动推荐发布。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                run_task_benchmark(
                    SUITE, root / "invalid", repeats=1,
                    arms=("myth", "context-full"),
                )
            self.assertFalse((root / "invalid").exists())
            report = run_task_benchmark(
                SUITE, root / "partial", repeats=1,
                arms=("context-baseline", "context-full"),
                case_ids=["arithmetic"],
            )
            self.assertFalse(report["complete_suite"])
            self.assertFalse(report["context_ablation"]["full_context_arms"])
            self.assertEqual(report["context_ablation"]["complete_pair_count"], 0)
            self.assertFalse(report["context_ablation"]["ready_for_separate_heldout_review"])

    # 回归断言：无效题号/重复次数在创建证据目录和业务 Run 前拒绝。
    def test_invalid_case_and_repeat_are_rejected_before_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            for repeats in (True, 0, 11):
                with self.assertRaises(ValueError):
                    run_task_benchmark(SUITE, Path(tmp) / "unused", repeats=repeats)
            with self.assertRaises(ValueError):
                run_task_benchmark(SUITE, Path(tmp) / "unused", case_ids=["missing"])


if __name__ == "__main__":
    unittest.main()
