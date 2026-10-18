"""离线语义消融 CLI：冻结 EvalSuite、复用现有 Ledger，退出码拒绝候选回归。

不连接任何模型，不提供自动 Promote；精确 Token/真实服务延迟需要另行跑 Provider A/B。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from myth.platform.evaluation_store import SqliteEvaluationLedger
from myth.runtime import MythRuntime
from myth.semantic_evaluation import SemanticAblationRunner


# main：先固定所有参数与套件，再运行独立 Oracle；出错不生成虚假的成功文件或状态。
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / "semantic-contract-v1.json",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--case-id", action="append", default=None)
    parser.add_argument(
        "--record-root", type=Path, default=None,
        help="Explicit optional persistent research ledger root; no production policy promotion.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    runner = SemanticAblationRunner.from_path(
        args.suite, repeats=args.repeats, seed=args.seed,
    )

    # 只有操作者显式指定 record-root 时才写入研究账本；其他情况每题为临时 SQLite。
    if args.record_root is not None:
        with MythRuntime(args.record_root) as runtime:
            report = runner.run(
                case_ids=tuple(args.case_id) if args.case_id is not None else None,
                ledger=SqliteEvaluationLedger(runtime),
            )
    else:
        report = runner.run(
            case_ids=tuple(args.case_id) if args.case_id is not None else None,
        )

    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        # 拒绝无意覆盖已存在的评测事实；产物不是发布资格。
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))

    # 固定全集/安全题一项失败即返回非零；partial 仅供诊断，同样不可声称验收成功。
    summary = report["summary"]
    qualified = (
        summary["complete_suite"]
        and summary["candidate_pass"] == summary["case_count"]
        and summary["candidate_unsafe_values"] == 0
        and summary["candidate_losses"] == 0
    )
    return 0 if qualified else 1


if __name__ == "__main__":
    sys.exit(main())
