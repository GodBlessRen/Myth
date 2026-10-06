"""受信测试 profile 的真实进程完成证据；退出码零不能替代非空测试执行。
临时 Python 文件刻画空发现、提前退出、全跳过及正常完成，不调用模型。
"""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace


class VerificationCompletionTests(unittest.TestCase):
    """测试结果必须同时拥有 runner 完成、实际测试数量与成功退出三项事实。"""

    # 每例建全新受信项目与固定 profile，测试目录不能借用真实仓库测试。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root / "runtime")
        self.workspace = Workspace(self.runtime)
        self.project_root = self.root / "project"
        self.test_dir = self.project_root / "tests"
        self.test_dir.mkdir(parents=True)
        self.project = self.workspace.repository.create_project({"name": "fixture", "root": str(self.project_root)})
        self.profile = self.workspace.verification.create(self.project["id"], {"trusted_project": True, "max_output_bytes": 4096, "timeout_seconds": 20})
        self.turn = {"snapshot": {"project": self.project}}

    # 释放真实连接后清理临时项目。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 直接运行固定 profile 的进程层，Tool Ticket 合同由既有 delivery 测试独立证明。
    def run_profile(self, source=None):
        if source is not None:
            (self.test_dir / "test_fixture.py").write_text(source, encoding="utf-8")
        return self.workspace.verification.run(self.turn, self.profile["profile_id"])

    # 发现零测试是未验证，不能为 completion 提供 PASS。
    def test_empty_discovery_is_not_passed(self):
        result = self.run_profile()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["completion_reason"], "no_executed_tests")
        self.assertEqual(result["test_count"], 0)

    # 测试导入时进程硬退出会越过 runner 收尾；进程成功不代表测试完成。
    def test_import_exit_zero_is_not_passed(self):
        result = self.run_profile("import os\nos._exit(0)\n")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["completion_reason"], "runner_incomplete")

    # 全部跳过依然没有执行验收断言；skip 不进入已执行测试分母。
    def test_all_skipped_is_not_passed(self):
        result = self.run_profile("import unittest\nclass Fixture(unittest.TestCase):\n @unittest.skip('fixture')\n def test_skipped(self): pass\n")
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["executed_test_count"], 0)

    # stderr 的头部可以超出展示预算；完成摘要从有界尾部读取，输出仍严格截断。
    def test_completion_survives_output_truncation(self):
        result = self.run_profile("import unittest,sys\nclass Fixture(unittest.TestCase):\n def test_ok(self):\n  sys.stderr.write('x'*10000+'\\n')\n  self.assertEqual(2+3,5)\n")
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["test_count"], 1)
        self.assertEqual(result["executed_test_count"], 1)
        self.assertTrue(result["stderr_truncated"])
        self.assertLessEqual(len(result["stderr"].encode("utf-8")), 4096)


if __name__ == "__main__":
    unittest.main()
