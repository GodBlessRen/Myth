"""回归边界：固定任务 Harness 及独立验收。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

import json
from pathlib import Path
import tempfile
import unittest

from myth.task_benchmark import run_task_benchmark


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
