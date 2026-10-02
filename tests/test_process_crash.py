from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from myth.runtime import MythRuntime


class HardProcessCrashTests(unittest.TestCase):
    def _run_child(self, root: Path, run_id: str, failpoint: str) -> subprocess.CompletedProcess[str]:
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

    def test_hard_exit_after_receipt_recovers_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as rt:
                run_id = rt.submit_patch(source, old_text="foo", new_text="bar", expected_count=1)
            child = self._run_child(root, run_id, "hard_after_receipt_before_settle")
            self.assertEqual(child.returncode, 92)
            with MythRuntime(root) as rt:
                [status] = rt.recover(run_id)
                self.assertEqual(status["state"], "SUCCEEDED")
                self.assertEqual(Path(status["managed_file"]).read_text(encoding="utf-8"), "bar")

    def test_hard_exit_after_write_before_receipt_keeps_usage_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as rt:
                run_id = rt.submit_patch(source, old_text="foo", new_text="bar", expected_count=1)
            child = self._run_child(root, run_id, "hard_after_write_before_receipt")
            self.assertEqual(child.returncode, 91)
            with MythRuntime(root) as rt:
                [status] = rt.recover(run_id)
                self.assertEqual(status["state"], "SUCCEEDED")
                accounts = {a["meter"]: a for a in status["budgets"]}
                self.assertEqual(accounts["tool_calls"]["unknown_held"], 1)


if __name__ == "__main__":
    unittest.main()
