"""核对真实发布归档：垃圾站、运行数据和淘汰入口不得随 wheel/sdist/源码 ZIP 交付。

只读取归档目录，不解压或执行；本模块拥有发布清单的比较规则，不拥有运行状态。
普通文件、唯一包根和完整当前资源同时成立才通过。安装 HTTP 验证仍由 validate_package.py 负责。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile


# 开发进度与本机数据同样不进入发布包；大小写变体也按 Windows 文件语义排除。
FORBIDDEN = {".trash", ".work", ".work-notes", ".runtime", "output", "__pycache__"}
# Win32 保留设备名也不能附扩展名；所有平台执行同一保守发布合同。
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + digit for prefix in ("COM", "LPT") for digit in "123456789¹²³"
}
# 已淘汰的生产模块不能因旧构建清单被重新装入 wheel。
RETIRED = {"platform/kernel.py", "platform/mcp.py", "platform/skills.py",
           "platform/workflow.py", "providers/capabilities.py"}


def _archive_entries(path: Path) -> list[tuple[str, bool]]:
    """返回名称与是否普通文件；目录可存在，链接/设备不能冒充离线资源。"""
    entries = []
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise ValueError(f"non-regular archive entry in {path.name}: {info.filename}")
                entries.append((info.filename, not info.is_dir() and kind != stat.S_IFDIR))
    else:
        with tarfile.open(path) as archive:
            for info in archive.getmembers():
                if not info.isfile() and not info.isdir():
                    raise ValueError(f"non-regular archive entry in {path.name}: {info.name}")
                entries.append((info.name, info.isfile()))
    return entries


def inspect_archive(path: Path) -> dict:
    """以本次源码清单核对一种归档；文件身份使用路径段与类型，不使用任意后缀。"""
    source = Path(__file__).resolve().parents[1] / "src/myth/webui"
    # 缺失源码或三个入口不能让清单悄悄缩成空集；这不替代完整 checkout/安装验证。
    if not source.is_dir() or any(not (source / name).is_file() for name in ("index.html", "app.js", "app.css")):
        raise ValueError("current web source is missing or lacks an entrypoint")
    entries = _archive_entries(path)
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
        if FORBIDDEN.intersection(part.casefold() for part in parts):
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
    if len(packages) != 1:
        raise ValueError(f"expected one complete package root in {path.name}, found {len(packages)}")
    files = next(iter(packages.values()))
    required = {"myth/adapters/knowledge_store.py", "myth/model_capabilities.py"}
    asset_types = {".html", ".css", ".js", ".svg", ".woff2", ".txt", ".png"}
    required.update("myth/webui/" + asset.relative_to(source).as_posix()
                    for asset in source.rglob("*") if asset.is_file() and asset.suffix in asset_types)
    # 集合差同时拒绝旧 build/lib 缓存和漏打包；不再为每个 required 扫一遍所有条目。
    current_assets = {item.removeprefix("myth/webui/") for item in required if item.startswith("myth/webui/")}
    archived_assets = {name.removeprefix("myth/webui/") for name in files
                       if name.startswith("myth/webui/") and PurePosixPath(name).suffix in asset_types}
    stale_assets = sorted(archived_assets - current_assets)
    if stale_assets:
        raise ValueError(f"stale static assets leaked into {path.name}: {stale_assets}")
    missing = sorted(required - files)
    if missing:
        raise ValueError(f"missing current files in {path.name}: {missing}")
    return {"archive": path.name, "entries": len(entries), "status": "PASS"}


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
