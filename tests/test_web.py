from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import re

from myth.agent_runtime import AgentRuntime
from myth.runtime import MythRuntime
from myth.web import ASSET_DIR, AgentWebService, serve


class WebSurfaceTests(unittest.TestCase):
    def test_packaged_web_assets_exist(self) -> None:
        for name in ("index.html", "app.css", "app.js", "inspector.js"):
            path = ASSET_DIR / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100)

    def test_v07_shell_preserves_app_contract_and_loads_inspector(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        app = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        required = set(re.findall(r'\\$\\("([^"]+)"\\)', app))
        missing = sorted(item for item in required if f'id="{item}"' not in html)
        self.assertEqual(missing, [])
        self.assertIn('<script src="/inspector.js"></script>', html)
        self.assertIn('id="runtimeInspector"', html)
        self.assertIn('id="executionSpine"', html)

    def test_web_server_rejects_non_loopback_bind(self) -> None:
        with self.assertRaises(ValueError):
            serve(".", host="0.0.0.0", port=0, open_browser=False)

    def test_empty_service_lists_no_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentWebService(Path(tmp))
            self.assertEqual(service.list_runs(), [])
            with MythRuntime(tmp) as runtime:
                self.assertEqual(AgentRuntime(runtime).list_runs(), [])


if __name__ == "__main__":
    unittest.main()
