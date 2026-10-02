"""CLI for durable local/file execution and P2 model decisions.

The CLI intentionally exposes no arbitrary shell. Provider credentials are
resolved by their adapters and never printed by Myth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .decision_runtime import DecisionRuntime
from .providers import create_provider
from .runtime import MythRuntime


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["ollama", "pi-openai", "openai"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--pi-command", default="pi")


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

    status = sub.add_parser("status", help="show persisted P1 file Run state")
    status.add_argument("run_id")

    recover = sub.add_parser("recover", help="reconcile unresolved file Tickets without blind replay")
    recover.add_argument("run_id", nargs="?")

    check = sub.add_parser("provider-check", help="check local/provider authentication readiness")
    _provider_args(check)

    plan = sub.add_parser("plan", help="make one durable LLM StepDecision; do not execute the proposal")
    _provider_args(plan)
    plan.add_argument("goal")
    plan.add_argument("--allow-file", action="append", default=[], type=Path)
    plan.add_argument("--context", default="")
    plan.add_argument("--max-output-tokens", type=int, default=1024)
    plan.add_argument("--thinking")
    plan.add_argument("--request-id")

    model_status = sub.add_parser("model-status", help="show durable model invocation and decision state")
    model_status.add_argument("run_id")

    recover_model = sub.add_parser("recover-model", help="settle durable model receipts without repeating uncertain calls")
    recover_model.add_argument("run_id", nargs="?")
    return parser


def _provider(args: argparse.Namespace):
    return create_provider(
        args.provider,
        ollama_base_url=args.ollama_url,
        pi_command=args.pi_command,
    )


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "provider-check":
        provider = _provider(args)
        _print(provider.check())
        return

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
        elif args.command == "plan":
            provider = _provider(args)
            provider_status = provider.check()
            if not provider_status.ready:
                raise SystemExit(
                    "provider is not ready: "
                    + json.dumps(provider_status.details or {}, ensure_ascii=False)
                )
            decisions = DecisionRuntime(runtime)
            allowed_files = tuple(args.allow_file)
            run_id = decisions.create_goal_run(
                goal=args.goal,
                provider_id=provider.provider_id,
                model_id=args.model,
                allowed_files=allowed_files,
                max_output_tokens=args.max_output_tokens,
                request_id=args.request_id,
            )
            decision_id, decision = decisions.request_decision(
                run_id=run_id,
                provider=provider,
                model=args.model,
                allowed_files=allowed_files,
                context=args.context,
                max_output_tokens=args.max_output_tokens,
                thinking=args.thinking,
            )
            _print(
                {
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "provider": provider.provider_id,
                    "model": args.model,
                    "decision": decision.serializable(),
                    "note": "proposal only: Myth has not executed any proposed tool",
                }
            )
        elif args.command == "model-status":
            _print(DecisionRuntime(runtime).status(args.run_id))
        elif args.command == "recover-model":
            _print(DecisionRuntime(runtime).recover(args.run_id))


if __name__ == "__main__":
    main()
