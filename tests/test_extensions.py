"""扩展边界回归：Skill、Hook 与可选 MCP 真实 stdio 链路。
核心测试不要求 MCP 依赖；真实 MCP 用例在可选依赖存在时运行，避免“代码存在但从未握手”的假完成。
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from myth.adapters.extension_config import LocalExtensionConfig
from myth.adapters.local_skills import LocalSkillLibrary
from myth.adapters.local_tool_hooks import LocalToolHooks
from myth.adapters.mcp_stdio import StdioMCPGateway, sdk_available


class ExtensionResourceTests(unittest.TestCase):
    """核对本机扩展资源的摘要绑定、策略合并与安全默认值。"""

    def test_skill_digest_binds_paged_load(self) -> None:
        """Skill 必须先发现摘要再分页加载，资源变化后旧摘要立即失效。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill_dir = root / ".myth" / "skills" / "review"
            skill_dir.mkdir(parents=True)
            path = skill_dir / "SKILL.md"
            path.write_text("---\nname: Review\ndescription: Check project\n---\n# Body\nhello", encoding="utf-8")
            library = LocalSkillLibrary(LocalExtensionConfig(root))

            listing = library.list_skills()
            self.assertEqual(len(listing["skills"]), 1)
            row = listing["skills"][0]
            loaded = library.load("review", row["digest"], 0, 12)
            self.assertEqual(loaded["skill_id"], "review")
            self.assertFalse(loaded["grants_capabilities"])
            self.assertEqual(loaded["offset"], 0)

            path.write_text(path.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "digest changed"):
                library.load("review", row["digest"])

    def test_file_hooks_merge_in_stable_priority_order(self) -> None:
        """声明式 Hook 必须按 priority/id 稳定排序，且禁用项仍保持只读目录身份。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".myth"
            directory.mkdir()
            (directory / "hooks.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "hooks": [
                            {"id": "observe-z", "phase": "after_tool", "tools": ["*"], "priority": 10, "enabled": False, "action": "observe"},
                            {"id": "deny-a", "phase": "before_tool", "tools": ["mcp.call"], "priority": -10, "action": "deny"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            hooks = LocalToolHooks(LocalExtensionConfig(root)).snapshot()
            self.assertEqual([hook.hook_id for hook in hooks], ["deny-a", "observe-z"])
            self.assertFalse(hooks[1].enabled)


@unittest.skipUnless(sdk_available(), 'requires myth-runtime[mcp]')
class MCPStdioIntegrationTests(unittest.TestCase):
    """用仓库自带 FastMCP 服务验证真实 SDK 握手、发现、schema 校验与一次调用。"""

    def test_local_demo_discovery_and_call(self) -> None:
        """真实 stdio 服务应能发现 add，并在同一配置摘要下返回 2+3 的成功结果。"""
        repo = Path(__file__).resolve().parents[1]
        server = repo / "examples" / "mcp_server.py"
        self.assertTrue(server.is_file())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / ".myth"
            directory.mkdir()
            (directory / "extensions.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mcp_servers": [
                            {
                                "id": "local-demo",
                                "enabled": True,
                                "transport": "stdio",
                                "command": sys.executable,
                                "args": [str(server)],
                                "allowed_tools": ["add"],
                                "timeout_seconds": 20,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gateway = StdioMCPGateway(LocalExtensionConfig(root))

            discovery = gateway.invoke(gateway.prepare("local-demo"))
            self.assertEqual(discovery["status"], "DISCOVERED")
            add = next(row for row in discovery["tools"] if row["name"] == "add")
            self.assertTrue(add["allowed"])
            self.assertIsInstance(add["input_schema"], dict)

            result = gateway.invoke(
                gateway.prepare(
                    "local-demo",
                    tool_name="add",
                    arguments={"a": 2, "b": 3},
                    discovery=discovery,
                )
            )
            self.assertEqual(result["status"], "RETURNED")
            self.assertEqual(result["tool_name"], "add")
            self.assertFalse(result["is_error"])
            self.assertTrue(result["content"] or result["structured_content"] is not None)


if __name__ == "__main__":
    unittest.main()
