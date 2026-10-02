"""Small CLI for the P1 runtime. It intentionally exposes no arbitrary shell."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import MythRuntime


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myth", description="Minimal durable Agent Runtime")
    parser.add_argument("--root", default=".", help="project root containing private .runtime state")
    sub = parser.add_subparsers(dest="command", required=True)

    patch = sub.add_parser("patch", help="submit and execute one exact managed-file replacement")
    patch.add_argument("source", type=Path)
    patch.add_argument("--old", required=True)
    patch.add_argument("--new", required=True)
    patch.add_argument("--count", required=True, type=int)
    patch.add_argument("--request-id")

    status = sub.add_parser("status", help="show persisted Run state")
    status.add_argument("run_id")

    recover = sub.add_parser("recover", help="reconcile unresolved Tickets without blind replay")
    recover.add_argument("run_id", nargs="?")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with MythRuntime(args.root) as runtime:
        if args.command == "patch":
            run_id = runtime.submit_patch(
                args.source,
                old_text=args.old,
                new_text=args.new,
                expected_count=args.count,
                request_id=args.request_id,
            )
            _print(runtime.execute(run_id))
        elif args.command == "status":
            _print(runtime.status(args.run_id))
        elif args.command == "recover":
            _print(runtime.recover(args.run_id))


if __name__ == "__main__":
    main()
