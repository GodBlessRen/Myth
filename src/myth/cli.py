"""CLI for P1 file execution, P2 model decisions, and the P3 Agent loop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_runtime import AgentRuntime
from .decision_runtime import DecisionRuntime
from .providers import create_provider
from .runtime import MythRuntime


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["scripted", "ollama", "pi-openai", "openai"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--pi-command", default="pi")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myth", description="Durable Agent Runtime")
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

    agent = sub.add_parser("agent", help="run the bounded durable Agent loop")
    _provider_args(agent)
    agent.add_argument("goal")
    agent.add_argument("--allow-file", action="append", required=True, type=Path)
    agent.add_argument("--max-steps", type=int, default=6)
    agent.add_argument("--max-output-tokens", type=int, default=1024)
    agent.add_argument("--thinking")
    agent.add_argument("--request-id")
    agent.add_argument("--acceptance", type=Path, help="UTF-8 JSON array of fixed exact replacement rules")

    advance = sub.add_parser("continue-agent", help="reconcile and continue a persisted Agent without repeating uncertain work")
    _provider_args(advance)
    advance.add_argument("run_id")

    answer = sub.add_parser("answer-agent", help="answer the current durable question")
    _provider_args(answer)
    answer.add_argument("run_id")
    answer.add_argument("question_id")
    answer.add_argument("text")

    cancel = sub.add_parser("cancel-agent", help="stop new work and delivery; preserve late execution facts")
    cancel.add_argument("run_id")

    sub.add_parser("demo", help="run a deterministic read/patch/verify demo; no LLM or credentials")

    agent_status = sub.add_parser("agent-status", help="show Agent decisions, receipts and verification")
    agent_status.add_argument("run_id")

    model_status = sub.add_parser("model-status", help="show durable model invocation and decision state")
    model_status.add_argument("run_id")

    recover_model = sub.add_parser("recover-model", help="settle durable model receipts without repeating uncertain calls")
    recover_model.add_argument("run_id", nargs="?")

    evaluate = sub.add_parser("eval", help="run a fixed local Myth evaluation suite")
    evaluate.add_argument("--suite", default="evals/foundation-v1.json")
    evaluate.add_argument("--case", action="append", default=[], dest="case_ids")

    web = sub.add_parser("web", help="start the local Myth Agent workspace")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-browser", action="store_true")
    return parser


def _provider(args: argparse.Namespace):
    return create_provider(
        args.provider,
        ollama_base_url=args.ollama_url,
        pi_command=args.pi_command,
    )


def _require_provider(args: argparse.Namespace):
    provider = _provider(args)
    status = provider.check()
    if not status.ready:
        raise SystemExit(
            "provider is not ready: "
            + json.dumps(status.details or {}, ensure_ascii=False)
        )
    return provider


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "provider-check":
        _print(_provider(args).check())
        return
    if args.command == "eval":
        from .evaluation_runner import run_eval_suite

        _print(run_eval_suite(args.suite, args.case_ids))
        return
    if args.command == "web":
        from .web import serve

        serve(
            args.root,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
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
            provider = _require_provider(args)
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
        elif args.command == "agent":
            provider = _require_provider(args)
            agent = AgentRuntime(runtime)
            run_id = agent.create_run(
                goal=args.goal,
                provider=provider,
                model=args.model,
                allowed_files=tuple(args.allow_file),
                max_steps=args.max_steps,
                max_output_tokens=args.max_output_tokens,
                thinking=args.thinking,
                request_id=args.request_id,
                acceptance=json.loads(args.acceptance.read_text(encoding="utf-8")) if args.acceptance else None,
            )
            _print(agent.run(run_id, provider))
        elif args.command == "continue-agent":
            _print(AgentRuntime(runtime).run(args.run_id, _require_provider(args)))
        elif args.command == "answer-agent":
            _print(AgentRuntime(runtime).resume(args.run_id, _require_provider(args), args.text, question_id=args.question_id))
        elif args.command == "cancel-agent":
            _print(AgentRuntime(runtime).cancel(args.run_id))
        elif args.command == "demo":
            from .demo import create_demo
            run_id, provider = create_demo(runtime)
            _print(AgentRuntime(runtime).run(run_id, provider))
        elif args.command == "agent-status":
            _print(AgentRuntime(runtime).status(args.run_id))
        elif args.command == "model-status":
            _print(DecisionRuntime(runtime).status(args.run_id))
        elif args.command == "recover-model":
            _print(DecisionRuntime(runtime).recover(args.run_id))


if __name__ == "__main__":
    main()
