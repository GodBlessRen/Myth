"""回归边界：纯模块依赖方向。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

import ast
from pathlib import Path
import unittest
import subprocess
import sys
import os


# 纯模块依赖方向的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ArchitectureTests(unittest.TestCase):
    # 独立无 site 进程导入纯领域；无需认证第三方库且不加载数据库/HTTP，防止顶层导出破坏纯模块边界。
    def test_pure_domain_import_does_not_load_io_or_auth_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        environment = {**os.environ, "PYTHONPATH": str(root / "src")}
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import myth.domain, sys; assert not {'sqlite3', 'urllib.request', 'jwt', 'keyring'} & set(sys.modules)",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    # 公开入口按需加载仍返回原类；目录发现未知名称也不触发新业务。
    def test_lazy_public_exports_preserve_class_identity_and_discovery(self):
        import myth
        from myth.agent_runtime import AgentRuntime
        from myth.runtime import MythRuntime
        from myth.platform import MythComponents

        for name, expected in (
            ("AgentRuntime", AgentRuntime),
            ("MythRuntime", MythRuntime),
            ("MythComponents", MythComponents),
        ):
            self.assertIs(getattr(myth, name), expected)
            self.assertIn(name, dir(myth))
        with self.assertRaises(AttributeError):
            getattr(myth, "missing_export")

    # 回归断言：遍历纯模块 import，阻止 Core/应用反向依赖文件、网络、SQL 和具体适配器。
    def test_agent_core_has_no_concrete_io_dependencies(self):
        root = Path(__file__).resolve().parents[1] / "src" / "myth"
        forbidden = {
            "sqlite3",
            "pathlib",
            "os",
            "subprocess",
            "urllib",
            "http",
            "socket",
            "adapters",
            "runtime",
            "store",
            "decision_runtime",
            "providers",
        }
        files = [
            root / "domain.py",
            root / "models.py",
            root / "model_capabilities.py",
            root / "platform/control.py",
            root / "acceptance.py",
            root / "ports.py",
            root / "conversation.py",
            root / "conversation_context.py",
            root / "conversation_ports.py",
            *sorted((root / "core").glob("*.py")),
            *sorted((root / "domains").glob("*.py")),
            *sorted((root / "strategies").glob("*.py")),
            *sorted((root / "application").glob("*.py")),
        ]
        for source in files:
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    self.assertTrue(
                        forbidden.isdisjoint(name.split(".")),
                        f"{source.name}:{node.lineno} imports {name}",
                    )
