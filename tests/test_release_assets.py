"""发布缓存回归：保留当前资源不能掩盖旧装饰的多余打包。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_validation", ROOT / "scripts/validate_release.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ReleaseAssetTests(unittest.TestCase):
    """读取真实当前资源构建固定归档，再模拟构建目录留下的旧 PNG。"""

    def archive(self, path: Path, *, stale: bool) -> None:
        """资源来自当前源码；仅额外 PNG 是模拟已删除缓存，不运行归档内代码。"""
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("adapters/knowledge_store.py", "model_capabilities.py"):
                archive.write(ROOT / "src/myth" / name, "myth/" + name)
            source = ROOT / "src/myth/webui"
            for asset in source.rglob("*"):
                if asset.is_file():
                    archive.write(asset, "myth/webui/" + asset.relative_to(source).as_posix())
            if stale:
                archive.writestr("myth/webui/images/paper-study.png", b"retired build cache")

    def test_current_assets_pass(self) -> None:
        """当前完整资源形成可发布归档，避免把新增嵌套字体误判为残留。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.whl"
            self.archive(path, stale=False)
            self.assertEqual(VALIDATOR.inspect_archive(path)["status"], "PASS")

    def test_deleted_decoration_rejected_even_with_all_current_assets(self) -> None:
        """重现所有新资源存在但旧纸构仍随 wheel 交付的构建缓存窗口。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.whl"
            self.archive(path, stale=True)
            with self.assertRaisesRegex(ValueError, "stale static assets.*paper-study"):
                VALIDATOR.inspect_archive(path)
