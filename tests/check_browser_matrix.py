"""兼容 Python 验收入口；复用 Node Playwright 与本机 Chrome，不下载浏览器。"""
from pathlib import Path
import subprocess
import sys


def main():
    """参数透传真实浏览器矩阵；子进程失败使当前门禁失败。"""
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(["node", str(root / "tests/browser_matrix.cjs"), *sys.argv[1:]], cwd=root, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
