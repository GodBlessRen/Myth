"""回归边界：包资源、HTTP 绑定与第三栏 DOM。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import re

from myth.agent_runtime import AgentRuntime
from myth.runtime import MythRuntime
from myth.web import ASSET_DIR, AgentWebService, serve


# 包资源、HTTP 绑定与第三栏 DOM的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class WebSurfaceTests(unittest.TestCase):
    # 回归断言：包内静态资源及 renderer 入口存在；只证明打包合同，不证明视觉质量。
    def test_packaged_web_assets_exist(self) -> None:
        for name in ("index.html", "app.css", "app.js", "inspector.js"):
            path = ASSET_DIR / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100)

    # 回归断言：既有 HTML id/脚本依赖和第三栏结构继续存在。
    def test_v07_shell_preserves_app_contract_and_loads_inspector(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        app = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        required = set(re.findall(r'\\$\\("([^"]+)"\\)', app))
        missing = sorted(item for item in required if f'id="{item}"' not in html)
        self.assertEqual(missing, [])
        self.assertIn('<script src="/inspector.js"></script>', html)
        self.assertIn('id="runtimeInspector"', html)
        self.assertIn('id="executionSpine"', html)

    # 回归断言：本地服务拒绝非 loopback 绑定，不能自动变成公网服务。
    def test_web_server_rejects_non_loopback_bind(self) -> None:
        with self.assertRaises(ValueError):
            serve(".", host="0.0.0.0", port=0, open_browser=False)

    # 回归断言：空数据库读列表不产生 Run 或虚构历史。
    def test_empty_service_lists_no_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentWebService(Path(tmp))
            self.assertEqual(service.list_runs(), [])
            with MythRuntime(tmp) as runtime:
                self.assertEqual(AgentRuntime(runtime).list_runs(), [])


if __name__ == "__main__":
    unittest.main()
