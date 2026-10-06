"""发布边界故障回归：临时源码与归档验证路径合同，不宣称真实 wheel 已构建。

测试使用独立资源清单，完整生产资源仍由 test_release_assets.py 和安装包检查覆盖。
归档只在临时目录创建；不解压恶意名称、链接或设备条目。
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_boundary_validation", ROOT / "scripts/validate_release.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class ReleaseBoundaryTests(unittest.TestCase):
    """每个用例独立拥有源码基准与坏归档，验证器仍执行实际生产实现。"""

    def setUp(self) -> None:
        """建立最小离线资源树；只替换清单根目录，不替换归档检查逻辑。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "src/myth/webui"
        self.assets = {
            "index.html": b"<html></html>", "app.js": b"'use strict';", "app.css": b"body {}",
            "icons/mark.svg": b"<svg></svg>", "licenses/NOTICE.txt": b"test fixture",
        }
        for name, data in self.assets.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        patcher = patch.object(VALIDATOR, "__file__", str(self.root / "scripts/validate_release.py"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def entries(self, prefix: str = "myth") -> dict[str, bytes]:
        """生成一种合法包根下的完整最小文件集；不包含真实应用或第三方字体。"""
        values = {prefix + "/adapters/knowledge_store.py": b"# fixture", prefix + "/model_capabilities.py": b"# fixture"}
        values.update({prefix + "/webui/" + name: data for name, data in self.assets.items()})
        return values

    def archive(self, name: str, entries: dict[str, bytes]) -> Path:
        """按指定格式写文件目录，验证时不得把这些不可信条目解压到磁盘。"""
        path = self.root / name
        if name.endswith(".tar.gz"):
            with tarfile.open(path, "w:gz") as archive:
                for filename, data in entries.items():
                    info = tarfile.TarInfo(filename)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        else:
            with zipfile.ZipFile(path, "w") as archive:
                for filename, data in entries.items():
                    info = zipfile.ZipInfo(filename)
                    # 故意恢复原始样本名，防止写入库提前修正待测危险路径。
                    info.filename = filename
                    archive.writestr(info, data)
        return path

    def test_valid_wheel_and_source_archive_layouts(self) -> None:
        """wheel、git archive ZIP、带顶层目录的源码 ZIP/sdist 均保留合法入口。"""
        layouts = (("ok.whl", "myth"), ("git.zip", "src/myth"),
                   ("github.zip", "Myth-current/src/myth"), ("source.tar.gz", "myth-runtime-0.27.0/src/myth"))
        for name, prefix in layouts:
            with self.subTest(name=name):
                self.assertEqual(VALIDATOR.inspect_archive(self.archive(name, self.entries(prefix)))["status"], "PASS")

    def test_work_directory_is_excluded_from_every_archive_format(self) -> None:
        """开发进度目录即使藏在包根内部，也不能进入三种发布归档。"""
        for name, prefix in (("bad.whl", "myth"), ("bad.zip", "src/myth"), ("bad.tar.gz", "source/src/myth")):
            with self.subTest(name=name):
                entries = self.entries(prefix)
                entries[prefix + "/.work/PROGRESS.md"] = b"private work notes"
                with self.assertRaisesRegex(ValueError, "excluded content"):
                    VALIDATOR.inspect_archive(self.archive(name, entries))

    def test_existing_exclusions_still_hold(self) -> None:
        """新增 .work 不得替代既有垃圾站、运行库、输出与字节码排除项。"""
        for folder in (".trash", ".runtime", "output", "__pycache__", ".WORK", ".work-notes"):
            with self.subTest(folder=folder):
                entries = self.entries()
                entries[folder + "/note"] = b"fixture"
                with self.assertRaisesRegex(ValueError, "excluded content"):
                    VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_similar_directory_names_are_not_overblocked(self) -> None:
        """按路径段而非子串排除；普通 .work-notes 文件不被误伤。"""
        entries = self.entries()
        entries["docs/.work-notes.md"] = b"public fixture"
        self.assertEqual(VALIDATOR.inspect_archive(self.archive("ok.whl", entries))["status"], "PASS")

    def test_missing_source_directory_cannot_shrink_manifest_to_zero(self) -> None:
        """源码未检出时 rglob 空集不能冒充无需静态资源。"""
        shutil.rmtree(self.source)
        entries = {name: data for name, data in self.entries().items() if "/webui/" not in name}
        with self.assertRaisesRegex(ValueError, "current web source"):
            VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_missing_source_entrypoint_fails_closed(self) -> None:
        """资源目录存在但入口缺失仍不可信；不能用不完整基准验收归档。"""
        (self.source / "index.html").unlink()
        with self.assertRaisesRegex(ValueError, "current web source"):
            VALIDATOR.inspect_archive(self.archive("bad.whl", self.entries()))

    def test_missing_current_asset_is_rejected(self) -> None:
        """当前清单中的嵌套图标漏打包必须失败。"""
        entries = self.entries()
        del entries["myth/webui/icons/mark.svg"]
        with self.assertRaisesRegex(ValueError, "missing current files"):
            VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_stale_asset_remains_rejected(self) -> None:
        """所有新资源齐全，也不能夹带已淘汰的旧装饰。"""
        entries = self.entries()
        entries["myth/webui/images/old.png"] = b"stale fixture"
        with self.assertRaisesRegex(ValueError, "stale static assets"):
            VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_retired_module_remains_rejected(self) -> None:
        """旧模块排除仍按真实路径段识别。"""
        entries = self.entries()
        entries["myth/platform/mcp.py"] = b"retired fixture"
        with self.assertRaisesRegex(ValueError, "retired module"):
            VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_suffix_lookalike_does_not_satisfy_required_files(self) -> None:
        """notmyth 结尾碰巧包含 myth，不代表真的提供 myth 包。"""
        with self.assertRaises(ValueError):
            VALIDATOR.inspect_archive(self.archive("bad.whl", self.entries("notmyth")))

    def test_multiple_package_roots_cannot_assemble_one_pass(self) -> None:
        """两个不完整源码树拼起来齐全，仍不是一个完整可发布包。"""
        entries = {}
        for index, (name, data) in enumerate(self.entries("src/myth").items()):
            entries[("one/" if index % 2 else "two/") + name] = data
        with self.assertRaisesRegex(ValueError, "package root"):
            VALIDATOR.inspect_archive(self.archive("bad.zip", entries))

    def test_source_layout_is_not_accepted_inside_wheel(self) -> None:
        """wheel 内藏 src/myth 不会被正常安装为 myth；后缀匹配不能放行。"""
        with self.assertRaises(ValueError):
            VALIDATOR.inspect_archive(self.archive("bad.whl", self.entries("src/myth")))

    def test_unsafe_path_names_are_rejected_without_extraction(self) -> None:
        """相对上溯、绝对路径、Windows 分隔符和盘符在读取目录时直接拒绝。"""
        for bad in ("../escape.txt", "/absolute.txt", "folder/../../escape.txt", "folder\\escape.txt", "C:/escape.txt", "docs/visible\x00hidden.txt"):
            with self.subTest(name=bad):
                entries = self.entries()
                entries[bad] = b"never extract"
                with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                    VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_original_zip_name_survives_platform_normalization(self) -> None:
        """真实 ZIP 目录保留原始名称；模拟 Windows 分隔符改写不能绕过验证。"""
        for bad in ("folder\\escape.txt", "docs/visible\x00hidden.txt"):
            with self.subTest(name=bad):
                entries = self.entries()
                entries[bad] = b"never extract"
                path = self.archive("raw.whl", entries)
                with patch("zipfile.os.sep", "\\"):
                    with zipfile.ZipFile(path) as archive:
                        self.assertEqual(archive.infolist()[-1].orig_filename, bad)
                        self.assertNotEqual(archive.infolist()[-1].filename, bad)
                    with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                        VALIDATOR.inspect_archive(path)

    def test_duplicate_zip_entry_is_rejected(self) -> None:
        """同名重复条目会令不同工具读取不同字节，不能视为唯一文件身份。"""
        path = self.archive("bad.whl", self.entries())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("myth/webui/index.html", b"different bytes")
        with self.assertRaisesRegex(ValueError, "duplicate archive path"):
            VALIDATOR.inspect_archive(path)

    def test_zip_symbolic_link_cannot_replace_resource(self) -> None:
        """归档中同名符号链接不是包内普通资源；不跟随链接检查目标。"""
        entries = self.entries()
        del entries["myth/webui/index.html"]
        path = self.archive("bad.whl", entries)
        with zipfile.ZipFile(path, "a") as archive:
            info = zipfile.ZipInfo("myth/webui/index.html")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"../../outside")
        with self.assertRaisesRegex(ValueError, "non-regular archive entry"):
            VALIDATOR.inspect_archive(path)

    def test_tar_links_and_devices_are_rejected(self) -> None:
        """sdist 的符号链接、硬链接和设备条目不能作为可移植文件交付。"""
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                path = self.root / "bad.tar.gz"
                with tarfile.open(path, "w:gz") as archive:
                    for name, data in self.entries("source/src/myth").items():
                        info = tarfile.TarInfo(name)
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
                    special = tarfile.TarInfo("source/special")
                    special.type = kind
                    special.linkname = "../../outside"
                    archive.addfile(special)
                with self.assertRaisesRegex(ValueError, "non-regular archive entry"):
                    VALIDATOR.inspect_archive(path)

    def test_tar_directory_cannot_satisfy_required_file(self) -> None:
        """名叫 index.html 的目录不是 HTML 文件，不能只比较归档名称。"""
        path = self.root / "bad.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data in self.entries("source/src/myth").items():
                info = tarfile.TarInfo(name)
                if name.endswith("/index.html"):
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        with self.assertRaisesRegex(ValueError, "missing current files"):
            VALIDATOR.inspect_archive(path)

    def test_case_collisions_are_rejected_for_files_and_parent_directories(self) -> None:
        """Linux 上不同的大小写路径在默认 Windows 上可能冲突，不能生成歧义包。"""
        for collision in ("MYTH/model_capabilities.py", "Myth/extra.py", "myth/ADAPTERS/extra.py"):
            with self.subTest(collision=collision):
                entries = self.entries()
                entries[collision] = b"collision fixture"
                with self.assertRaisesRegex(ValueError, "case-colliding"):
                    VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_windows_reserved_and_ambiguous_names_are_rejected(self) -> None:
        """按 Win32 可移植名称约束拒绝设备名、尾空格/句点及保留字符；未在 Windows 实测。"""
        names = ("NUL.txt", "com1.log", "LPT9", "COM\u00b9.txt", "con", "AUX.data", "PRN.txt",
                 "file.", "dir /file.txt", "file ", "bad?.txt", "bad*.txt", 'bad".txt',
                 "bad<.txt", "bad>.txt", "bad|.txt")
        for name in names:
            with self.subTest(name=name):
                entries = self.entries()
                entries["docs/" + name] = b"never extract"
                with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                    VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_regular_file_cannot_be_parent_of_another_entry(self) -> None:
        """文件与同名目录前缀冲突必须与条目顺序无关地拒绝。"""
        for file_first in (True, False):
            with self.subTest(file_first=file_first):
                entries = self.entries()
                extra = {"docs": b"file", "docs/note.md": b"child"}
                entries.update(extra if file_first else dict(reversed(list(extra.items()))))
                with self.assertRaisesRegex(ValueError, "file/directory conflict"):
                    VALIDATOR.inspect_archive(self.archive("bad.whl", entries))

    def test_regular_tar_member_cannot_use_directory_spelling(self) -> None:
        """普通 TAR 文件末尾带斜杠是类型与名称冲突，不得只去掉斜杠后放行。"""
        entries = self.entries("source/src/myth")
        entries["source/src/myth/webui/index.html/"] = entries.pop("source/src/myth/webui/index.html")
        with self.assertRaisesRegex(ValueError, "unsafe archive path"):
            VALIDATOR.inspect_archive(self.archive("bad.tar.gz", entries))

    def test_ordinary_unicode_names_and_explicit_directories_remain_valid(self) -> None:
        """限制危险名称不等于只准 ASCII；中文文件和显式目录仍允许。"""
        entries = self.entries()
        entries.update({"docs/": b"", "docs/说明.md": b"public fixture", "docs/COM10.txt": b"ordinary name"})
        self.assertEqual(VALIDATOR.inspect_archive(self.archive("ok.whl", entries))["status"], "PASS")
