"""回归边界：组件架构投影。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


# 组件架构投影的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class PlatformWebTests(unittest.TestCase):
    # 回归断言：Workspace/Web 组件地图一致，避免 UI 维护另一套架构事实。
    def test_workspace_and_web_expose_same_composable_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                direct = Workspace(runtime).components.snapshot()
            web = ConversationWebService(root).platform()

            self.assertEqual(web["version"], direct["version"])
            self.assertEqual(web["shape"], "core-domains-strategies-adapters")
            self.assertEqual(
                web["executable_capabilities"], direct["executable_capabilities"]
            )

            domains = {item["id"]: item["maturity"] for item in web["domains"]}
            self.assertEqual(domains["control"], "usable")
            self.assertEqual(domains["personal"], "connected")
            adapters = {item["id"]: item["maturity"] for item in web["adapters"]}
            self.assertNotIn("a2a", adapters)
            self.assertNotIn("mcp", adapters)
            self.assertNotIn("browser", adapters)
            self.assertNotIn("shell.exec", web["executable_capabilities"])


if __name__ == "__main__":
    unittest.main()
