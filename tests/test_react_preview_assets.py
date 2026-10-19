"""React 预览版包内文件身份：构建 manifest 是唯一静态输入，不扫描 URL。

不安装 Node，不联网，不运行模型。默认 / 仍归旧版，/next/ 必须来自同一套 wheel 资源。
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from myth.web_assets import PUBLIC_ASSETS

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "myth" / "webui"


class ReactPreviewAssetsTest(unittest.TestCase):
    """校验旧版根目录回退与 React 离线预览拥有不同的资源身份。"""
    def test_legacy_root_and_preview_are_distinct(self):
        """禁止未声明路径公开，旧入口必须保持原生工作台。"""
        self.assertEqual(PUBLIC_ASSETS["/"][0], "index.html")
        self.assertEqual(PUBLIC_ASSETS["/next/"][0], "react/index.html")
        self.assertEqual(PUBLIC_ASSETS["/next"][0], "react/index.html")
        self.assertEqual(PUBLIC_ASSETS["/next/workbench.js"][0], "react/workbench.js")
        self.assertNotIn("/next/manifest.json", PUBLIC_ASSETS)
        self.assertNotIn("/next/package-lock.json", PUBLIC_ASSETS)
        self.assertNotIn("/next/other.js", PUBLIC_ASSETS)

    def test_vendored_output_matches_manifest(self):
        """核对安装前 React 三份构建资源与不可变 SHA256 清单一致。"""
        directory = WEB / "react"
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["format"], 1)
        self.assertEqual(set(manifest["files"]), {"index.html", "workbench.js", "workbench.css"})
        for filename, metadata in manifest["files"].items():
            data = (directory / filename).read_bytes()
            self.assertEqual(len(data), metadata["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), metadata["sha256"])
        html = (directory / "index.html").read_text("utf-8")
        self.assertIn("/next/workbench.js", html)
        self.assertIn("/next/workbench.css", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_staging_normalizes_windows_line_endings_before_hashing(self):
        """Windows 构建进入 LF checkout 后，清单摘要仍须逐字节一致。"""
        spec = importlib.util.spec_from_file_location("stage_react_preview", ROOT / "scripts/stage_react_preview.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            dist = directory / "dist"
            dist.mkdir()
            outputs = {
                "index.html": b'<script src="/next/workbench.js"></script>\r\n<link href="/next/workbench.css">\r\n',
                "workbench.js": b'console.log("ready");\r\n',
                "workbench.css": b'body { margin: 0; }\r\n',
            }
            for name, content in outputs.items():
                (dist / name).write_bytes(content)
            dest = directory / "staged"
            manifest = module.stage(dist, dest)
            for name in outputs:
                content = (dest / name).read_bytes()
                self.assertNotIn(b"\r", content)
                self.assertEqual(manifest["files"][name]["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(manifest["files"][name]["bytes"], len(content))
            self.assertNotIn(b"\r", (dest / "manifest.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
