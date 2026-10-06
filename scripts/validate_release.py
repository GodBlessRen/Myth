"""核对真实发布归档：垃圾站、运行数据和淘汰入口不得随 wheel/sdist/源码 ZIP 交付。

只读取归档目录与内容，不落盘解压或执行；本模块拥有发布清单，不拥有运行状态。
普通文件、唯一包根、完整路径集与当前字节同时成立才通过；安装 HTTP 另由 validate_package.py 验证。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tarfile
import zipfile


# 开发进度与本机数据同样不进入发布包；大小写变体也按 Windows 文件语义排除。
FORBIDDEN = {".trash", ".work", ".work-notes", ".runtime", ".myth", ".git", "secrets", "output", "__pycache__"}
# 与本机数据边界一致；只检查名称，不在错误中输出文件内容或凭据。
PRIVATE_SUFFIXES = (".pem", ".key", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite-wal",
                    ".sqlite-shm", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".pyc", ".pyo")
# 仅 Git 已记录 LF 的已知文本可采用导出换行；图片、字体及未知二进制始终逐字节比较。
GIT_TEXT_SUFFIXES = {".py", ".js", ".cjs", ".html", ".css", ".svg", ".json", ".txt", ".md", ".toml", ".in", ".cfg", ".ps1"}
# Win32 保留设备名也不能附扩展名；所有平台执行同一保守发布合同。
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}
# 已淘汰的生产模块不能因旧构建清单被重新装入 wheel。
RETIRED = {"platform/kernel.py", "platform/mcp.py", "platform/skills.py",
           "platform/workflow.py", "providers/capabilities.py"}


def _archive_entries(path: Path, archive: zipfile.ZipFile | tarfile.TarFile) -> list[tuple[str, bool]]:
    """返回名称与是否普通文件；目录可存在，链接/设备不能冒充离线资源。"""
    entries = []
    if isinstance(archive, zipfile.ZipFile):
        for info in archive.infolist():
            # 使用原始目录名；ZipInfo.filename 会截断 NUL 并在 Windows 改写反斜杠。
            name = info.orig_filename
            kind = stat.S_IFMT(info.external_attr >> 16)
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"non-regular archive entry in {path.name}: {name}")
            entries.append((name, not info.is_dir() and kind != stat.S_IFDIR))
    else:
        for info in archive.getmembers():
            if not info.isfile() and not info.isdir():
                raise ValueError(f"non-regular archive entry in {path.name}: {info.name}")
            entries.append((info.name, info.isfile()))
    return entries


def _private_path(parts: list[str] | tuple[str, ...]) -> bool:
    """路径任一层命中私有目录/文件便拒绝，避免移到 dist-info 旁边绕过包内检查。"""
    return any(part.casefold() in FORBIDDEN or part.casefold().endswith(PRIVATE_SUFFIXES)
               or (part.casefold().startswith(".env") and part.casefold() != ".env.example"
                   and (part.casefold() == ".env" or part.casefold().startswith(".env.")))
               for part in parts)


def _current_tree(directory: Path) -> dict[str, Path]:
    """收集完整当前文件树；缓存不属源码，链接或私有数据不能成为可信比较基准。"""
    if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
        raise ValueError(f"current source directory is missing or linked: {directory.name}")
    files = {}
    for item in sorted(directory.rglob("*")):
        relative = item.relative_to(directory)
        # 编译/测试会生成这些文件；排除它们不扩大归档侧的接纳范围。
        if "__pycache__" in relative.parts or item.suffix in {".pyc", ".pyo"}:
            continue
        if item.is_symlink() or item.is_junction():
            raise ValueError(f"non-regular current source: {relative.as_posix()}")
        if _private_path(relative.parts):
            raise ValueError(f"excluded content in current source: {relative.as_posix()}")
        if item.is_dir():
            continue
        if not stat.S_ISREG(item.stat().st_mode):
            raise ValueError(f"non-regular current source: {relative.as_posix()}")
        files[relative.as_posix()] = item
    return files


def _git_text_paths(root: Path) -> set[str]:
    """只读 Git 的换行事实；无 Git 的源码目录严格比较原字节，不运行 clean/smudge 过滤器。"""
    try:
        top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                      stderr=subprocess.DEVNULL, timeout=10).decode().strip()
        if Path(top).resolve() != root.resolve():
            return set()
        rows = subprocess.check_output(["git", "-C", str(root), "ls-files", "--eol", "-z", "--",
                                        "src/myth", "scripts", "tests", "pyproject.toml", "MANIFEST.in", "setup.py", "setup.cfg"],
                                       stderr=subprocess.DEVNULL, timeout=10).split(b"\0")
    except (FileNotFoundError, subprocess.CalledProcessError):
        return set()
    paths = set()
    for row in rows:
        metadata, _, name = row.partition(b"\t")
        relative = name.decode("utf-8", errors="surrogateescape")
        fields = metadata.split()
        if (fields[:1] == [b"i/lf"] and fields[1:2] in ([b"w/lf"], [b"w/crlf"]) and b"-text" not in metadata
                and Path(relative).suffix in GIT_TEXT_SUFFIXES):
            paths.add(relative)
    return paths


def _verify_contents(path: Path, archive: zipfile.ZipFile | tarfile.TarFile,
                     required: dict[str, Path], root: Path) -> dict[str, int]:
    """先核对长度，再有界读取与 SHA-256 对照；只读已验证的同一归档句柄且绝不执行内容。"""
    exported_text = _git_text_paths(root) if path.suffix == ".zip" else set()
    total = 0
    normalized = 0
    for name, source in sorted(required.items()):
        expected = source.read_bytes()
        candidates = {expected}
        if source.relative_to(root).as_posix() in exported_text:
            # Git archive 会受 core.eol/属性影响；仅允许两种明确换行编码，其他字节不能变。
            lf = expected.replace(b"\r\n", b"\n")
            candidates.update((lf, lf.replace(b"\n", b"\r\n")))
        info = archive.getinfo(name) if isinstance(archive, zipfile.ZipFile) else archive.getmember(name)
        size = info.file_size if isinstance(info, zipfile.ZipInfo) else info.size
        expected_digests = {hashlib.sha256(candidate).digest() for candidate in candidates if len(candidate) == size}
        if not expected_digests:
            raise ValueError(f"content mismatch in {path.name}: {name} (size)")
        digest = hashlib.sha256()
        with (archive.open(info) if isinstance(archive, zipfile.ZipFile) else archive.extractfile(info)) as stream:
            remaining = size
            while remaining:
                chunk = stream.read(min(remaining, 65536))
                if not chunk:
                    raise ValueError(f"content mismatch in {path.name}: {name} (truncated)")
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise ValueError(f"content mismatch in {path.name}: {name} (excess bytes)")
        if digest.digest() not in expected_digests:
            raise ValueError(f"content mismatch in {path.name}: {name} (sha256)")
        normalized += digest.digest() != hashlib.sha256(expected).digest()
        total += size
    return {"verified_files": len(required), "verified_bytes": total, "git_eol_files": normalized}


def _inspect_archive(path: Path, archive: zipfile.ZipFile | tarfile.TarFile, root: Path) -> dict:
    """名称/类型先通过，再核对唯一包根、完整文件集合及内容；归档不能提供自己的可信清单。"""
    source = root / "src/myth/webui"
    # 基准缺失不得收缩成空清单；完整 checkout 本身仍由调用方提供。
    if not source.is_dir() or any(not (source / name).is_file() for name in ("index.html", "app.js", "app.css")):
        raise ValueError("current web source is missing or lacks an entrypoint")
    entries = _archive_entries(path, archive)
    seen: set[str] = set()
    spellings: dict[str, str] = {}
    regular_paths: set[str] = set()
    parent_paths: set[str] = set()
    packages: dict[tuple[str, ...], set[str]] = {}
    for name, regular in entries:
        # 不先 normalize；否则上溯、重复分隔符或 Windows 名称可能被悄悄改写。
        canonical = name[:-1] if name.endswith("/") else name
        parts = canonical.split("/")
        if (not canonical or "\\" in canonical or any(ord(char) < 32 or ord(char) == 127 for char in canonical)
                or (regular and name.endswith("/"))
                or any(part in {"", ".", ".."} or part.endswith((" ", "."))
                       or any(char in '<>:"|?*' for char in part)
                       or part.partition(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICES
                       for part in parts)):
            raise ValueError(f"unsafe archive path in {path.name}: {name}")
        if canonical in seen:
            raise ValueError(f"duplicate archive path in {path.name}: {name}")
        seen.add(canonical)
        # 路径各级共享同一拼写；也检查隐式父目录，不依赖归档中的条目顺序。
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            folded = prefix.casefold()
            if spellings.setdefault(folded, prefix) != prefix:
                raise ValueError(f"case-colliding archive path in {path.name}: {name}")
            if depth < len(parts):
                if folded in regular_paths:
                    raise ValueError(f"file/directory conflict in {path.name}: {name}")
                parent_paths.add(folded)
        if regular:
            if canonical.casefold() in parent_paths:
                raise ValueError(f"file/directory conflict in {path.name}: {name}")
            regular_paths.add(canonical.casefold())
        if _private_path(parts):
            raise ValueError(f"excluded content leaked into {path.name}: {name}")
        if any(canonical == "myth/" + retired or canonical.endswith("/myth/" + retired) for retired in RETIRED):
            raise ValueError(f"retired module leaked into {path.name}: {name}")
        if not regular:
            continue
        # 当前 wheel 在根目录安装 myth；源码归档允许 src/myth 或一个顶层目录/src/myth。
        if path.suffix == ".whl" and parts[0] == "myth":
            offset = 0
        elif path.suffix != ".whl" and parts[:2] == ["src", "myth"]:
            offset = 1
        elif path.suffix != ".whl" and parts[1:3] == ["src", "myth"]:
            offset = 2
        else:
            continue
        packages.setdefault(tuple(parts[:offset]), set()).add("/".join(parts[offset:]))
    if path.suffix == ".whl":
        # wheel 的 .data/purelib 重定位与顶层 .pth 可绕过普通 myth 根；当前项目不发布这些入口。
        unexpected = sorted(name for name, regular in entries if regular and name.split("/")[0] != "myth"
                            and not ("/" in name and name.split("/")[0].endswith(".dist-info")))
        if unexpected:
            raise ValueError(f"unexpected wheel payload in {path.name}: {unexpected}")
    if len(packages) != 1:
        raise ValueError(f"expected one complete package root in {path.name}, found {len(packages)}")
    package_root, files = next(iter(packages.items()))
    current = {"myth/" + name: item for name, item in _current_tree(root / "src/myth").items()}
    if not {"myth/__init__.py", "myth/cli.py", "myth/web.py"}.issubset(current):
        raise ValueError("current package source is missing an entrypoint")
    # 全文件集合避免 Python 深层模块、JSON、许可和新扩展名逃过旧后缀白名单。
    stale = files - current.keys()
    stale_assets = sorted(name for name in stale if name.startswith("myth/webui/"))
    if stale_assets:
        raise ValueError(f"stale static assets leaked into {path.name}: {stale_assets}")
    if stale:
        raise ValueError(f"stale package files leaked into {path.name}: {sorted(stale)}")
    required = {"/".join((*package_root, name)): item for name, item in current.items()}
    unexpected_source = []
    if path.suffix != ".whl":
        # 源码发布必须能重跑当前门禁；脚本与测试必须同属于本包根，不能在别的树补齐。
        support = {name: root / name for name in ("pyproject.toml", "MANIFEST.in")}
        support.update({name: root / name for name in ("setup.py", "setup.cfg") if (root / name).exists()})
        for folder in ("scripts", "tests"):
            support.update({folder + "/" + name: item for name, item in _current_tree(root / folder).items()})
        if any(not item.is_file() or item.is_symlink() for item in support.values()):
            raise ValueError("current source build configuration is missing or linked")
        if not {"scripts/validate_release.py", "scripts/check_web.cjs"}.issubset(support):
            raise ValueError("current source validation gate is missing")
        source_root = package_root[:-1]
        required.update({"/".join((*source_root, name)): item for name, item in support.items()})
        prefix = "/".join(source_root) + "/" if source_root else ""
        for name, regular in entries:
            if not regular:
                continue
            relative = name.removeprefix(prefix)
            parts = relative.split("/")
            # 当前构建从 src 寻包；额外的包或旧 setup 配置同样能改变安装结果。
            if (not name.startswith(prefix)
                    or (relative in {"setup.py", "setup.cfg"} and relative not in support)
                    or (parts[0] == "src" and len(parts) > 1 and parts[1] != "myth"
                        and not parts[1].endswith(".egg-info"))):
                unexpected_source.append(name)
        for folder in ("scripts", "tests"):
            prefix = "/".join((*source_root, folder)) + "/"
            stale_support = sorted(name for name, regular in entries if regular and name.startswith(prefix) and name not in required)
            if stale_support:
                raise ValueError(f"stale source files leaked into {path.name}: {stale_support}")
    missing = sorted(required.keys() - {name for name, regular in entries if regular})
    if missing:
        raise ValueError(f"missing current files in {path.name}: {missing}")
    if unexpected_source:
        raise ValueError(f"unexpected source build path in {path.name}: {sorted(unexpected_source)}")
    evidence = _verify_contents(path, archive, required, root)
    return {"archive": path.name, "entries": len(entries), "status": "PASS", **evidence}


def inspect_archive(path: Path) -> dict:
    """wheel/sdist 比较工作树字节，Git ZIP 按已证实的文本换行事实比较导出字节。"""
    root = Path(__file__).resolve().parents[1]
    # 名称检查与内容检查共享句柄，避免先关后开的路径替换窗口。
    with (zipfile.ZipFile(path) if path.suffix in {".whl", ".zip"} else tarfile.open(path)) as archive:
        return _inspect_archive(path, archive, root)


def main() -> None:
    """检查指定目录或单个归档；空目录拒绝成功，便于 CI 固定构建与核对顺序。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    paths = ([args.path] if args.path.is_file() else sorted(
        path for path in args.path.iterdir() if path.name.endswith((".whl", ".tar.gz", ".zip"))
    ))
    if not paths:
        raise ValueError("no release archives found")
    print(json.dumps({"status": "PASS", "archives": [inspect_archive(path) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
