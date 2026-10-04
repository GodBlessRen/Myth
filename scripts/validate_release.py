"""核对真实发布归档：垃圾站、运行数据和淘汰入口不得随 wheel/sdist/源码 ZIP 交付。

只读取已构建文件；检查排除边界和完整静态资源，不执行包内代码。
安装后的实际 HTTP/API 验证由 validate_package.py 负责。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


# 项目检索和发布共享这条边界；历史资料只在开发 checkout 留档。
FORBIDDEN = {".trash", ".runtime", "output", "__pycache__"}
# 已淘汰的生产模块不能因旧构建清单被重新装入 wheel。
RETIRED = {"platform/kernel.py", "platform/mcp.py", "platform/skills.py",
           "platform/workflow.py", "providers/capabilities.py"}


def inspect_archive(path: Path) -> dict:
    """读取归档名而不解压；按路径段检查排除项，再核对当前模块与每份静态资源。"""
    if path.suffix in {".whl", ".zip"}:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path) as archive:
            names = archive.getnames()
    for name in names:
        if FORBIDDEN.intersection(PurePosixPath(name).parts):
            raise ValueError(f"excluded content leaked into {path.name}: {name}")
        if any(name.endswith("myth/" + retired) for retired in RETIRED):
            raise ValueError(f"retired module leaked into {path.name}: {name}")
    required = {"myth/adapters/knowledge_store.py", "myth/model_capabilities.py"}
    source = Path(__file__).resolve().parents[1] / "src/myth/webui"
    required.update("myth/webui/" + asset.name for asset in source.iterdir() if asset.is_file())
    missing = sorted(item for item in required if not any(name.endswith(item) for name in names))
    if missing:
        raise ValueError(f"missing current files in {path.name}: {missing}")
    return {"archive": path.name, "entries": len(names), "status": "PASS"}


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
