"""将 Vite 构建严格冻结成可审计的 Myth 本机 React 静态资源。

该脚本不下载依赖、不访问网络、不写主工作区；构建依赖由外层 CI 以只读权限处理。
未知 chunk 直接失败，防止文件存在却没有进入 HTTP 包内显式白名单。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

FILES = ("index.html", "workbench.js", "workbench.css")


def stage(dist: Path, dest: Path) -> dict:
    """仅允许三个固定构建输出，计算文件摘要后写入预览包，拒绝其他资源。"""
    dist = dist.resolve()
    actual = {
        item.relative_to(dist).as_posix()
        for item in dist.rglob("*")
        if item.is_file()
    }
    if actual != set(FILES):
        raise ValueError(f"unexpected Vite outputs: {sorted(actual ^ set(FILES))}")
    if any((dist / name).is_symlink() for name in FILES):
        raise ValueError("symlinks are not valid release assets")
    html = (dist / "index.html").read_text(encoding="utf-8")
    for url in ("/next/workbench.js", "/next/workbench.css"):
        if url not in html:
            raise ValueError(f"React index references missing fixed asset: {url}")
    if "http://" in html or "https://" in html:
        raise ValueError("React index must use offline, same-origin assets")
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "files": {}}
    for name in FILES:
        content = (dist / name).read_bytes()
        if not content:
            raise ValueError("empty built asset: " + name)
        (dest / name).write_bytes(content)
        manifest["files"][name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--out", type=Path, default=Path("src/myth/webui/react"))
    args = parser.parse_args()
    print(json.dumps(stage(args.dist, args.out), indent=2))
