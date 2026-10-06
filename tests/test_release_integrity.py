"""真实当前文件的发布合同回归；只生成测试归档，不运行构建、安装或浏览器。

独立遍历生产源码与门禁，验证完整性及测量分母；不把合成归档称为 setuptools 产物。
"""

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("current_release_validation", ROOT / "scripts/validate_release.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class CurrentReleaseIntegrityTests(unittest.TestCase):
    """用真实项目的全部非缓存文件构造样本，保持与临时最小树回归独立。"""

    def current_files(self, *, source: bool) -> dict[str, Path]:
        """直接扫描允许发布的当前目录；不调用验证器的清单函数生成断言输入。"""
        files = {}
        for folder in (("src/myth", "scripts", "tests") if source else ("src/myth",)):
            for item in (ROOT / folder).rglob("*"):
                if item.is_file() and "__pycache__" not in item.parts and item.suffix not in {".pyc", ".pyo"}:
                    name = item.relative_to(ROOT if source else ROOT / "src").as_posix()
                    files[name] = item
        if source:
            files.update({name: ROOT / name for name in ("pyproject.toml", "MANIFEST.in")})
        return files

    def test_complete_current_wheel_payload_is_verified(self) -> None:
        """所有生产源码与离线资源均参与字节核对；修改字体不需要维护测试名单。"""
        files = self.current_files(source=False)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "current.whl"
            with zipfile.ZipFile(path, "w") as archive:
                for name, item in files.items():
                    archive.writestr(name, item.read_bytes())
            result = VALIDATOR.inspect_archive(path)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_files"], len(files))
        self.assertEqual(result["verified_bytes"], sum(item.stat().st_size for item in files.values()))
        self.assertEqual(result["git_eol_files"], 0)

    def test_complete_current_sdist_payload_contains_web_gate_and_tests(self) -> None:
        """真实脚本和测试随当前包根交付；合成 sdist 的文件数、字节数使用独立分母。"""
        files = self.current_files(source=True)
        self.assertIn("scripts/check_web.cjs", files)
        self.assertIn("tests/test_web_gate_ui.cjs", files)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "current.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for name, item in files.items():
                    data = item.read_bytes()
                    info = tarfile.TarInfo("myth-current/" + name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            result = VALIDATOR.inspect_archive(path)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_files"], len(files))
        self.assertEqual(result["verified_bytes"], sum(item.stat().st_size for item in files.values()))
