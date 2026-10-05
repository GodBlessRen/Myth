"""开发门禁：先发现所有 unittest，用导入失败快速阻止后续耗时步骤。

只拥有本次检查的临时 TestLoader，不改测试、包或运行库。发现阶段会执行测试模块的
顶层代码，但不运行测试方法；因此仅用于已信任的仓库，且绝不替代完整测试门禁。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest


def main(argv: list[str] | None = None) -> int:
    """返回进程退出码；空集、导入错误和测试模块提前退出都不能冒充成功。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-dir", type=Path, default=Path(__file__).resolve().parents[1] / "tests")
    start = parser.parse_args(argv).start_dir.resolve()
    if not start.is_dir():
        print("Test discovery directory does not exist.", file=sys.stderr)
        return 1
    loader = unittest.TestLoader()
    try:
        # 与完整门禁使用相同发现模式；错误会成为 loader.errors，不能只数用例。
        suite = loader.discover(str(start), pattern="test_*.py")
        count = suite.countTestCases()
    except (ImportError, OSError, ValueError, SystemExit):
        # 即便模块在导入时 sys.exit(0)，也不代表发现流程完成。
        print("Test discovery aborted before completion.", file=sys.stderr)
        return 1
    if loader.errors:
        # 仅报告错误数量；详细 traceback 交给完整 unittest，避免再复制异常正文。
        print(f"Test discovery aborted before completion: {len(loader.errors)} import/load error(s).", file=sys.stderr)
        print("Run python -m unittest discover -s tests -v for the traceback.", file=sys.stderr)
        return 1
    if count == 0:
        print("Test discovery found no test cases.", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "phase": "discovery_only", "test_cases": count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
