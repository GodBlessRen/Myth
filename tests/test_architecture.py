"""依赖方向守卫：纯领域、端口和 Agent 用例不能反向依赖 I/O 适配器。"""
import ast
from pathlib import Path
import unittest


class ArchitectureTests(unittest.TestCase):
    def test_agent_core_has_no_concrete_io_dependencies(self):
        root=Path(__file__).resolve().parents[1]/"src"/"myth"
        forbidden={"sqlite3","pathlib","os","subprocess","urllib","http","socket","adapters","runtime","store","decision_runtime","providers"}
        files=[root/"acceptance.py",root/"ports.py",*sorted((root/"application").glob("*.py"))]
        for source in files:
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node,ast.Import):names=[alias.name for alias in node.names]
                elif isinstance(node,ast.ImportFrom):names=[node.module or ""]
                else:continue
                for name in names:
                    self.assertTrue(forbidden.isdisjoint(name.split(".")),f"{source.name}:{node.lineno} imports {name}")
