"""回归边界：长任务浸泡工具的健康路径与 UNKNOWN no-replay。
测试只跑秒级 quick 模式；2–3 小时真实 wall-clock 浸泡由同一脚本参数化执行，不把 CI 秒级结果冒充长跑证据。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


# 长任务浸泡 CLI 的秒级合同测试；真实长跑仍需显式执行 120–180 分钟配置。
class LongRunSoakTests(unittest.TestCase):
    # 调用实际脚本并解析 JSON；失败时保留 stdout/stderr 便于定位 Runtime 边界。
    def run_soak(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(__file__).resolve().parents[1] / "scripts" / "soak_long_run.py"
            command = [
                sys.executable,
                str(script),
                "--root",
                tmp,
                "--duration-minutes",
                "0.002",
                "--tool-steps",
                "3",
                "--poll-seconds",
                "0.05",
                *extra,
            ]
            child = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
            return json.loads(child.stdout)

    # 回归断言：单一 Run 在多个模型/工具 checkpoint 后完整结束，模型/工具计量与计划一致。
    def test_quick_healthy_soak_completes_one_run(self):
        report = self.run_soak()
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["tool_calls_settled"], 3)
        self.assertEqual(report["model_calls_settled"], 4)
        self.assertEqual(report["model_calls_unknown"], 0)
        self.assertGreaterEqual(report["cursor"]["checkpoint_step"], 4)

    # 回归断言：Ticket 后不明 provider 故障进入 UNKNOWN，后续 Executor tick 不自动重复调用。
    def test_quick_fault_soak_stops_unknown_without_replay(self):
        report = self.run_soak("--fault-call", "2")
        self.assertEqual(report["status"], "UNKNOWN")
        self.assertTrue(report["no_replay_after_unknown"])
        self.assertGreater(report["model_calls_unknown"], 0)


if __name__ == "__main__":
    unittest.main()
