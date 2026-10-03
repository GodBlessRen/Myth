"""回归边界：真实子进程硬退出窗口。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from myth.runtime import MythRuntime


# 真实子进程硬退出窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class HardProcessCrashTests(unittest.TestCase):
    # 真实子进程硬退出窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def _run_child(
        self, root: Path, run_id: str, failpoint: str
    ) -> subprocess.CompletedProcess[str]:
        code = (
            "from myth.runtime import MythRuntime; "
            f"r=MythRuntime({str(root)!r}); "
            f"r.execute({run_id!r}, failpoint={failpoint!r})"
        )
        env = os.environ.copy()
        src = str(Path(__file__).resolve().parents[1] / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    # 回归断言：真实子进程在收据后退出，恢复复用收据不再次写文件。
    def test_hard_exit_after_receipt_recovers_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as rt:
                run_id = rt.submit_patch(
                    source, old_text="foo", new_text="bar", expected_count=1
                )
            child = self._run_child(root, run_id, "hard_after_receipt_before_settle")
            self.assertEqual(child.returncode, 92)
            with MythRuntime(root) as rt:
                [status] = rt.recover(run_id)
                self.assertEqual(status["state"], "SUCCEEDED")
                self.assertEqual(
                    Path(status["managed_file"]).read_text(encoding="utf-8"), "bar"
                )

    # 回归断言：写后日志前硬退出按字节解决效果，但实际用量仍未知。
    def test_hard_exit_after_write_before_receipt_keeps_usage_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as rt:
                run_id = rt.submit_patch(
                    source, old_text="foo", new_text="bar", expected_count=1
                )
            child = self._run_child(root, run_id, "hard_after_write_before_receipt")
            self.assertEqual(child.returncode, 91)
            with MythRuntime(root) as rt:
                [status] = rt.recover(run_id)
                self.assertEqual(status["state"], "SUCCEEDED")
                accounts = {a["meter"]: a for a in status["budgets"]}
                self.assertEqual(accounts["tool_calls"]["unknown_held"], 1)


if __name__ == "__main__":
    unittest.main()
