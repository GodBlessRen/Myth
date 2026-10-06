"""以真实 Git 检查开发目录排除；只操作临时仓库，不修改当前分支或远端。

git archive 读取真实 .gitattributes；git check-ignore 读取真实 .gitignore。
这不构建 Myth wheel/sdist，不把排除策略通过称为安装包验收。
"""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_export_validation", ROOT / "scripts/validate_release.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class SourceExportPolicyTests(unittest.TestCase):
    """最小临时仓库只保留待验策略和固定非秘密样本，Git 本身不替换。"""

    def setUp(self) -> None:
        """拥有临时工作树；显式设置提交者和无签名模式，不读用户 Git 身份。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.git("init", "-q")

    def git(self, *args: str) -> bytes:
        """只对本用例临时目录执行固定参数；无 shell、remote、push 或强制操作。"""
        return subprocess.check_output([
            "git", "-c", "user.name=Myth export test", "-c", "user.email=export-test@localhost",
            "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "-c", "core.hooksPath=",
            "-C", str(self.repository), *args,
        ], stderr=subprocess.STDOUT, timeout=20)

    def test_git_archive_excludes_tracked_work_trash_and_output(self) -> None:
        """即使开发目录已经受跟踪，也必须被 export-ignore 排除，而非仅依赖未 add。"""
        (self.repository / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
        for name in (".work/PROGRESS.md", ".work-notes/MAP.md", ".trash/old.txt", "output/log.txt", "src/current.py"):
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed non-secret fixture", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "Fixture for source archive exclusion")
        archive = self.root / "source.zip"
        self.git("archive", "--format=zip", "--output=" + str(archive), "HEAD")
        with zipfile.ZipFile(archive) as opened:
            names = opened.namelist()
        self.assertIn("src/current.py", names)
        self.assertFalse(any(set(name.split("/")) & {".work", ".work-notes", ".trash", "output"} for name in names))

    def test_progress_is_ignored_without_hiding_production_source(self) -> None:
        """.work 进度默认不入库，但正常源码不能被宽泛规则一并隐藏。"""
        (self.repository / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
        for name in (".work/PROGRESS.md", ".work-notes/MAP.md", "src/current.py"):
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixed non-secret fixture", encoding="utf-8")
        matched = self.git("check-ignore", "--", ".work/PROGRESS.md", ".work-notes/MAP.md", "src/current.py").decode("utf-8").splitlines()
        self.assertEqual(matched, [".work/PROGRESS.md", ".work-notes/MAP.md"])

    def source_fixture(self) -> dict[str, bytes]:
        """固定可发布文件与 Git 属性；不用验证器生成期望，避免清单遗漏自我证明。"""
        files = {
            "src/myth/__init__.py": b"# fixture package\n",
            "src/myth/cli.py": b"# cli fixture\n",
            "src/myth/web.py": b"# web fixture\n",
            "src/myth/feature/current.py": b"# current nested module\n",
            "src/myth/webui/index.html": b"<html>fixture</html>\n",
            "src/myth/webui/app.js": b"// fixture\n",
            "src/myth/webui/app.css": b"body {}\n",
            "src/myth/webui/fonts/test.woff2": b"wOF2\x00\r\nfixture\n",
            "scripts/validate_release.py": b"# fixture validator\n",
            "scripts/check_web.cjs": b"// fixture gate\n",
            "tests/test_current.py": b"# fixture regression\n",
            "pyproject.toml": b"[build-system]\nrequires = ['setuptools>=68']\n",
            "MANIFEST.in": b"graft src/myth\ngraft scripts\ngraft tests\n",
            ".gitattributes": b"* text=auto\n*.woff2 -text\n",
        }
        for name, data in files.items():
            path = self.repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "Current source integrity fixture")
        return files

    def test_real_git_export_accepts_proven_text_eol_but_preserves_binary(self) -> None:
        """真实 Git 的 LF blob 与 Windows CRLF 工作树等价；字体中的 CRLF 不得改写。"""
        files = self.source_fixture()
        for name, data in files.items():
            if name.endswith((".py", ".js", ".css", ".html", ".cjs", ".toml", ".in")):
                (self.repository / name).write_bytes(data.replace(b"\n", b"\r\n"))
        archive = self.root / "source.zip"
        self.git("archive", "--format=zip", "--prefix=Myth-current/", "--output=" + str(archive), "HEAD")
        with patch.object(VALIDATOR, "__file__", str(self.repository / "scripts/validate_release.py")):
            result = VALIDATOR.inspect_archive(archive)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_files"], len(files) - 1)
        self.assertEqual(result["git_eol_files"], len(files) - 2)
        with zipfile.ZipFile(archive) as opened:
            self.assertEqual(opened.read("Myth-current/src/myth/webui/fonts/test.woff2"), files["src/myth/webui/fonts/test.woff2"])

    def test_git_crlf_export_can_be_checked_from_lf_source(self) -> None:
        """Git 的显式 CRLF 导出同样可核对，不能把 Windows 原生换行误判为内容篡改。"""
        files = self.source_fixture()
        archive = self.root / "source.zip"
        self.git("-c", "core.eol=crlf", "archive", "--format=zip", "--output=" + str(archive), "HEAD")
        with patch.object(VALIDATOR, "__file__", str(self.repository / "scripts/validate_release.py")):
            result = VALIDATOR.inspect_archive(archive)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["git_eol_files"], len(files) - 2)

    def test_uncommitted_semantic_change_is_not_hidden_by_git_eol_policy(self) -> None:
        """Git 清单只说明换行，不可用旧 blob 冒充已改动的当前源码字节。"""
        self.source_fixture()
        archive = self.root / "source.zip"
        self.git("archive", "--format=zip", "--output=" + str(archive), "HEAD")
        (self.repository / "src/myth/feature/current.py").write_bytes(b"# changed nested module\r\n")
        with patch.object(VALIDATOR, "__file__", str(self.repository / "scripts/validate_release.py")):
            with self.assertRaisesRegex(ValueError, "content mismatch.*feature/current.py"):
                VALIDATOR.inspect_archive(archive)

    def test_export_ignore_cannot_silently_drop_current_source(self) -> None:
        """真实 export-ignore 误排除了仍在当前源码树中的模块时，验收必须失败。"""
        self.source_fixture()
        with (self.repository / ".gitattributes").open("ab") as stream:
            stream.write(b"src/myth/feature/current.py export-ignore\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-q", "-m", "Inject an invalid source exclusion")
        archive = self.root / "source.zip"
        self.git("archive", "--format=zip", "--output=" + str(archive), "HEAD")
        with patch.object(VALIDATOR, "__file__", str(self.repository / "scripts/validate_release.py")):
            with self.assertRaisesRegex(ValueError, "missing current files.*feature/current.py"):
                VALIDATOR.inspect_archive(archive)

    def test_git_export_does_not_normalize_changed_binary_bytes(self) -> None:
        """工作树字体 CRLF 被替换也是真实内容改变，不得套用文本换行豁免。"""
        files = self.source_fixture()
        archive = self.root / "source.zip"
        self.git("archive", "--format=zip", "--output=" + str(archive), "HEAD")
        font = "src/myth/webui/fonts/test.woff2"
        (self.repository / font).write_bytes(files[font].replace(b"\r\n", b"\n"))
        with patch.object(VALIDATOR, "__file__", str(self.repository / "scripts/validate_release.py")):
            with self.assertRaisesRegex(ValueError, "content mismatch.*test.woff2"):
                VALIDATOR.inspect_archive(archive)
