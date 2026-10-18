"""Semantic Contract 最后收官评测：真实 SQLite 行为、冻结 Oracle、配对账本与发布隔离。

这组夹具验证离线规则与报告的可靠性，不把无模型选择器评测写成真实 Agent 质量提升。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from myth.platform.evaluation import EvalCase, EvalSuite
from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.runtime import MythRuntime
from myth.semantic_evaluation import SemanticAblationRunner


# SUITE：使用仓库中先行冻结、独立于被测 Runner 的 Oracle JSON，而不是从当前代码生成预期。
SUITE = Path(__file__).resolve().parents[1] / "evals" / "semantic-contract-v1.json"


# SemanticEvaluationTests：公开 Runner 接口即测试面；不窥探中间 SQL 或为了测试改写业务代码。
class SemanticEvaluationTests(unittest.TestCase):
    # 每个案例只有一个独立 ID；同一 Case 的重复测量不增加成功率分母。
    def test_full_suite_complete_and_descriptive_only(self):
        outcome = SemanticAblationRunner.from_path(SUITE, repeats=3, seed=11).run()
        summary = outcome["summary"]
        self.assertEqual(summary["case_count"], 16)
        self.assertEqual(summary["measured_case_count"], 16)
        self.assertEqual(summary["candidate_pass"], 16)
        self.assertEqual(summary["baseline_pass"], 8)
        self.assertEqual(summary["candidate_wins"], 8)
        self.assertEqual(summary["candidate_losses"], 0)
        self.assertEqual(summary["candidate_ties"], 8)
        self.assertEqual(summary["baseline_unsafe_values"], 8)
        self.assertEqual(summary["candidate_unsafe_values"], 0)
        self.assertTrue(summary["complete_suite"])
        self.assertFalse(summary["release_eligible"])
        self.assertFalse(summary["model_quality_claim"])
        self.assertIsNone(summary["token_usage"])
        self.assertIsNone(summary["provider_cost"])
        self.assertEqual(len(summary["suite_sha256"]), 64)
        for arm in ("bare_selector", "semantic_contract"):
            payload = outcome["variants"][arm]
            self.assertTrue(payload["complete_suite"])
            self.assertEqual(payload["selected_case_count"], 16)
            self.assertFalse(payload["release_gate"]["passed"])
            self.assertEqual(payload["evaluation_partition"], "discovery")
            self.assertEqual(len(payload["observations"]), 16)
        for case in outcome["cases"]:
            self.assertGreaterEqual(case["setup_ms"], 0)
            self.assertGreaterEqual(case["semantic_contract"]["p95_ms"], 0)
            self.assertEqual(case["semantic_contract"]["verdict"], "PASS")

    # 从真实 Ledger 读取双臂结果，检查固定分母/版本/配对身份与 release 不可用。
    def test_existing_evaluation_ledger_keeps_full_paired_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            with MythRuntime(Path(folder)) as runtime:
                ledger = SqliteEvaluationLedger(runtime)
                outcome = SemanticAblationRunner.from_path(SUITE).run(ledger=ledger)
                runs = outcome["summary"]["evaluation_run_ids"]
                before = ledger.run(runs["bare_selector"])
                after = ledger.run(runs["semantic_contract"])
                self.assertEqual(before["suite_case_count"], 16)
                self.assertEqual(after["suite_case_count"], 16)
                self.assertEqual(before["evaluation_partition"], "discovery")
                self.assertEqual(after["evaluation_partition"], "discovery")
                self.assertEqual(len(before["observations"]), 16)
                self.assertEqual(len(after["observations"]), 16)
                pairs = ledger.paired_comparisons(
                    runs["bare_selector"], runs["semantic_contract"],
                )
                self.assertEqual(len(pairs), 16)
                self.assertEqual(len({p.case_id for p in pairs}), 16)
                self.assertTrue(all(p.comparison_key.startswith(
                    outcome["summary"]["suite_sha256"]
                ) for p in pairs))
                with self.assertRaises(ValueError):
                    ledger.require_held_out_final(runs["semantic_contract"])

    # 单题选取只能用于调试，完整题集分母不变，禁止以 partial 资格冒充发布结果。
    def test_filtered_suite_is_not_complete_even_when_selected_case_passes(self):
        runner = SemanticAblationRunner.from_path(SUITE)
        partial = runner.run(case_ids=("s01-scalar",))
        self.assertEqual(partial["summary"]["measured_case_count"], 1)
        self.assertEqual(partial["summary"]["case_count"], 16)
        self.assertFalse(partial["summary"]["complete_suite"])
        self.assertEqual(partial["summary"]["candidate_pass"], 1)
        self.assertFalse(partial["variants"]["semantic_contract"]["release_gate"]["passed"])

    # Oracle 更改后必须更改套件摘要；错误与缺题不能被选例过滤或低级摘要掩盖。
    def test_suite_identity_reflects_oracle_and_rejects_bad_selections(self):
        runner = SemanticAblationRunner.from_path(SUITE)
        altered_first = replace(runner.suite.cases[0], expected={"status": "resolved", "value": 0})
        changed = EvalSuite(
            runner.suite.suite_id, runner.suite.version,
            runner.suite.principle, (altered_first, *runner.suite.cases[1:]),
        )
        alternate = SemanticAblationRunner(changed)
        self.assertNotEqual(alternate.suite_digest, runner.suite_digest)
        with self.assertRaisesRegex(ValueError, "unknown"):
            runner.run(case_ids=("not-a-case",))
        with self.assertRaisesRegex(ValueError, "duplicates"):
            runner.run(case_ids=("s01-scalar", "s01-scalar"))

    # 用损坏预期模拟隐藏验收回归：Candidate 不能通过篡改报告自动获得完全胜利。
    def test_incorrect_oracle_surfaces_candidate_fail_and_safety_regression(self):
        runner = SemanticAblationRunner.from_path(SUITE)
        target = next(c for c in runner.suite.cases if c.case_id == "s09-unit-mismatch")
        changed = replace(target, expected={"status": "resolved", "value": 20})
        cases = tuple(changed if x.case_id == target.case_id else x for x in runner.suite.cases)
        suite = EvalSuite(runner.suite.suite_id, runner.suite.version, runner.suite.principle, cases)
        result = SemanticAblationRunner(suite).run(case_ids=(target.case_id,))
        self.assertEqual(result["summary"]["candidate_pass"], 0)
        self.assertEqual(result["variants"]["semantic_contract"]["report"]["fail_count"], 1)
        self.assertEqual(
            result["variants"]["semantic_contract"]["report"]["safety_regressions"], 1,
        )
        self.assertFalse(result["summary"]["release_eligible"])

    # 重复测量次数必须不扩张独立样本量，负载/延迟统计只属于本机离线微观比较。
    def test_repeats_and_order_do_not_change_candidate_oracle(self):
        first = SemanticAblationRunner.from_path(SUITE, repeats=2, seed=7).run(
            case_ids=("s11-source-conflict",),
        )
        second = SemanticAblationRunner.from_path(SUITE, repeats=5, seed=19).run(
            case_ids=("s11-source-conflict",),
        )
        self.assertEqual(first["summary"]["measured_case_count"], 1)
        self.assertEqual(second["summary"]["measured_case_count"], 1)
        self.assertEqual(first["summary"]["candidate_pass"], second["summary"]["candidate_pass"])
        self.assertEqual(first["summary"]["candidate_wins"], second["summary"]["candidate_wins"])
        self.assertNotEqual(first["summary"]["repeats"], second["summary"]["repeats"])


if __name__ == "__main__":
    unittest.main()
