"""发现门禁的子进程回归；临时测试树不是 Myth 全套测试或真实模型证据。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DiscoveryGateTests(unittest.TestCase):
    """每次启动新解释器，避免 sys.modules 缓存掩盖第二次导入失败。"""

    def invoke(self, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """生成独立已信任测试树并运行真实脚本；测试正文不能在发现时执行。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(ROOT / "scripts/check_test_discovery.py"), "--start-dir", str(root)],
                cwd=root, capture_output=True, text=True, timeout=15,
            )

    def test_success_counts_cases_without_running_test_bodies(self) -> None:
        """用必定失败的正文证明 PASS 仅指发现完成，不是测试方法通过。"""
        result = self.invoke({"test_cases.py":
            "import unittest\nclass Cases(unittest.TestCase):\n"
            "    def test_one(self): raise AssertionError('must not execute')\n"
            "    def test_two(self): raise AssertionError('must not execute')\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "PASS", "phase": "discovery_only", "test_cases": 2})

    def test_missing_import_fails_before_test_execution(self) -> None:
        """重现导入已不存在的 Message；被发现的 _FailedTest 不能算正常用例。"""
        result = self.invoke({
            "models_fixture.py": "class ModelRequest: pass\n",
            "test_claude_oauth.py": "from models_fixture import ModelRequest, Message\n",
        })
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 import/load error(s)", result.stderr)
        self.assertNotIn("PASS", result.stdout)

    def test_syntax_error_fails(self) -> None:
        """语法不合法仍必须阻断，不能因为测试对象没构造出来就被漏算。"""
        result = self.invoke({"test_bad.py": "def broken(:\n"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("import/load error", result.stderr)

    def test_empty_suite_fails(self) -> None:
        """误指空目录不能造成绿色零测试。"""
        result = self.invoke({})
        self.assertEqual(result.returncode, 1)
        self.assertIn("no test cases", result.stderr)

    def test_load_tests_error_fails(self) -> None:
        """unittest 的自定义发现钩子出错也要走失败路径。"""
        result = self.invoke({"test_hook.py":
            "def load_tests(loader, tests, pattern):\n    raise RuntimeError('fixture failure')\n"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("import/load error", result.stderr)

    def test_import_time_success_exit_is_not_discovery_success(self) -> None:
        """测试模块意外 exit(0) 必须被门禁转为失败，而不是绕过检查。"""
        result = self.invoke({"test_exit.py": "raise SystemExit(0)\n"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("aborted before completion", result.stderr)

    def test_nested_package_is_discovered(self) -> None:
        """嵌套测试包沿用 unittest 原有规则，不能只检查顶层模块。"""
        result = self.invoke({
            "nested/__init__.py": "",
            "nested/test_nested.py": "import unittest\nclass Case(unittest.TestCase):\n    def test_ok(self): pass\n",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["test_cases"], 1)

    def test_missing_directory_fails(self) -> None:
        """不存在的测试入口明确失败；不让异常路径变成未运行的 PASS。"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check_test_discovery.py"), "--start-dir", str(Path(directory) / "missing")],
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stderr)
