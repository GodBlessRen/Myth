"""以真实 Git 检查开发目录排除；只操作临时仓库，不修改当前分支或远端。

git archive 读取真实 .gitattributes；git check-ignore 读取真实 .gitignore。
这不构建 Myth wheel/sdist，不把排除策略通过称为安装包验收。
"""

from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


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
            "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", "-c", "core.hooksPath=",
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
