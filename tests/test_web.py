"""回归边界：包资源、HTTP 绑定与第三栏 DOM。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
from http.server import ThreadingHTTPServer
import threading
import tempfile
import unittest
import re
from urllib.request import urlopen
from urllib.error import HTTPError

from myth.agent_runtime import AgentRuntime
from myth.runtime import MythRuntime
from myth.web import ASSET_DIR, AgentWebService, make_handler, serve


# 包资源、HTTP 绑定与第三栏 DOM的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class WebSurfaceTests(unittest.TestCase):
    # 回归断言：包内静态资源及 renderer 入口存在；只证明打包合同，不证明视觉质量。
    def test_packaged_web_assets_exist(self) -> None:
        for name in ("index.html", "app.css", "app.js", "studio.js", "taiji.svg", "inspector.js", "goals.js", "statistics.js", "reconnect.js", "theme.js", "favicon.svg", "fonts/myth-sans.woff2", "fonts/myth-serif.woff2", "fonts/myth-latin.woff2", "fonts/OFL-NotoSansSC.txt", "fonts/OFL-NotoSerifSC.txt", "fonts/OFL-Manrope.txt"):
            path = ASSET_DIR / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100)

    # 回归断言：既有 HTML id/脚本依赖和第三栏结构继续存在。
    def test_v07_shell_preserves_app_contract_and_loads_inspector(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        app = "\n".join((ASSET_DIR / name).read_text(encoding="utf-8") for name in ("app.js", "inspector.js", "goals.js"))
        required = set(re.findall(r'\$\("([^"]+)"\)', app))
        missing = sorted(item for item in required if f'id="{item}"' not in html)
        self.assertEqual(missing, [])
        self.assertIn('<script src="/inspector.js"></script>', html)
        self.assertIn('id="runtimeInspector"', html)
        self.assertIn('id="executionSpine"', html)

    # 固定资源由真实 Handler 提供，首屏主题不能因 CSP 或遗漏打包再次闪白。
    def test_theme_bootstrap_and_icon_are_served_under_existing_csp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentWebService(Path(tmp))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(base + "/", timeout=3) as response:
                    html = response.read().decode("utf-8")
                    self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
                    self.assertLess(html.index('src="/theme.js"'), html.index('href="/app.css"'))
                    self.assertNotRegex(html, r"<script(?![^>]*src=)[^>]*>\s*\S")
                for path, content_type in (("/theme.js", "text/javascript"), ("/studio.js", "text/javascript"), ("/taiji.svg", "image/svg+xml"), ("/favicon.svg", "image/svg+xml"), ("/fonts/myth-sans.woff2", "font/woff2"), ("/fonts/myth-serif.woff2", "font/woff2"), ("/fonts/myth-latin.woff2", "font/woff2")):
                    with urlopen(base + path, timeout=3) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(content_type, response.headers["Content-Type"])
                        body = response.read()
                        self.assertGreater(len(body), 100)
                        if content_type == "font/woff2":
                            self.assertEqual(body[:4], b"wOF2")
                            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                # 新静态路径不得变成通用文件服务器；未知字体和编码后的穿越均不公开文件。
                for path in ("/fonts/unknown.woff2", "/fonts/%2e%2e/web.py", "/fonts/OFL-NotoSansSC.txt"):
                    with self.assertRaises(HTTPError) as rejected:
                        urlopen(base + path, timeout=3)
                    self.assertEqual(rejected.exception.code, 404)
                self.assertEqual(service.list_runs(), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)
                service.workspace.stop_scheduler()

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
