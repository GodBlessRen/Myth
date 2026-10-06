"""命令行装配入口。
解析明确用户意图并调用 Runtime、Workspace、认证、评测与策略发布用例；CLI 不复制事务规则，也不把替身结果称为真实模型质量。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent_runtime import AgentRuntime
from .decision_runtime import DecisionRuntime
from .providers import create_provider
from .runtime import MythRuntime


# 输出 JSON 数据投影，保持中文可读；调用方负责只提供可公开内容。
def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


# 解析显式 meter=weight 参数；不自动替用户发明多维成本归一化权重。
def _weights(values):
    result = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit("weight must use meter=value")
        meter, value = raw.split("=", 1)
        meter = meter.strip()
        if not meter:
            raise SystemExit("weight meter cannot be empty")
        try:
            result[meter] = float(value)
        except ValueError as exc:
            raise SystemExit("weight value must be numeric") from exc
    return result


# 给命令添加供应商/模型/预算参数；认证秘钥不作为持久命令字段。
def _provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider", choices=["scripted", "ollama", "chatgpt", "openai", "deepseek", "anthropic", "kimi"], required=True
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")


# 定义公开命令和有界参数；业务事务与权限规则仍留在对应用例。
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myth", description="Durable Agent Runtime")
    parser.add_argument(
        "--root", default=".", help="project root containing private .runtime state"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    patch = sub.add_parser(
        "patch", help="submit and execute one exact managed-file replacement"
    )
    patch.add_argument("source", type=Path)
    patch.add_argument("--old", required=True)
    patch.add_argument("--new", required=True)
    patch.add_argument("--count", required=True, type=int)
    patch.add_argument("--request-id")

    status = sub.add_parser("status", help="show persisted P1 file Run state")
    status.add_argument("run_id")

    recover = sub.add_parser(
        "recover", help="reconcile unresolved file Tickets without blind replay"
    )
    recover.add_argument("run_id", nargs="?")

    check = sub.add_parser(
        "provider-check", help="check local/provider authentication readiness"
    )
    _provider_args(check)
    auth_login = sub.add_parser(
        "auth-login", help="sign in to ChatGPT using Myth-owned OAuth"
    )
    auth_login.add_argument("--profile-id")
    auth_login.add_argument("--no-browser", action="store_true")
    sub.add_parser("auth-status", help="show ChatGPT OAuth status without secrets")
    auth_logout = sub.add_parser(
        "auth-logout", help="revoke and clear the active ChatGPT OAuth session"
    )
    auth_logout.add_argument("--profile-id")

    plan = sub.add_parser(
        "plan", help="make one durable LLM StepDecision; do not execute the proposal"
    )
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
    agent.add_argument(
        "--acceptance",
        type=Path,
        help="UTF-8 JSON array of fixed exact replacement rules",
    )

    advance = sub.add_parser(
        "continue-agent",
        help="reconcile and continue a persisted Agent without repeating uncertain work",
    )
    _provider_args(advance)
    advance.add_argument("run_id")

    answer = sub.add_parser("answer-agent", help="answer the current durable question")
    _provider_args(answer)
    answer.add_argument("run_id")
    answer.add_argument("question_id")
    answer.add_argument("text")

    cancel = sub.add_parser(
        "cancel-agent", help="stop new work and delivery; preserve late execution facts"
    )
    cancel.add_argument("run_id")

    sub.add_parser(
        "demo", help="run a deterministic read/patch/verify demo; no LLM or credentials"
    )

    agent_status = sub.add_parser(
        "agent-status", help="show Agent decisions, receipts and verification"
    )
    agent_status.add_argument("run_id")

    model_status = sub.add_parser(
        "model-status", help="show durable model invocation and decision state"
    )
    model_status.add_argument("run_id")

    recover_model = sub.add_parser(
        "recover-model",
        help="settle durable model receipts without repeating uncertain calls",
    )
    recover_model.add_argument("run_id", nargs="?")

    evaluate = sub.add_parser("eval", help="run a fixed local Myth evaluation suite")
    evaluate.add_argument("--suite", default="evals/foundation-v4.json")
    evaluate.add_argument("--case", action="append", default=[], dest="case_ids")
    evaluate.add_argument("--policy-id", default="production-default")
    evaluate.add_argument(
        "--resolution-policy", choices=["default", "L0", "L1", "L2"], default="default"
    )
    evaluate.add_argument("--record", action="store_true")

    tasks = sub.add_parser(
        "task-benchmark",
        help="run fixed daily tasks and persist every trial, including failures",
    )
    tasks.add_argument("--suite", default="evals/daily-v1.json")
    tasks.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new evidence directory; never overwrites a run",
    )
    tasks.add_argument(
        "--provider",
        choices=["scripted", "ollama", "openai", "chatgpt", "deepseek", "anthropic", "kimi"],
        default="scripted",
    )
    tasks.add_argument("--model", default="fixture")
    tasks.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    tasks.add_argument("--repeats", type=int, default=3)
    tasks.add_argument("--arm", action="append", choices=["myth", "simple-loop"])
    tasks.add_argument("--case", action="append", default=[], dest="case_ids")

    history = sub.add_parser(
        "eval-history", help="show persisted local evaluation runs"
    )
    history.add_argument("--limit", type=int, default=20)

    compare = sub.add_parser(
        "eval-compare", help="compare two persisted evaluation runs case by case"
    )
    compare.add_argument("baseline_eval_run_id")
    compare.add_argument("candidate_eval_run_id")

    gain = sub.add_parser(
        "gain", help="estimate paired information gain for one fixed eval case"
    )
    gain.add_argument("baseline_eval_run_id")
    gain.add_argument("candidate_eval_run_id")
    gain.add_argument("case_id")
    gain.add_argument("--source-ref")
    gain.add_argument("--from-resolution", choices=["L0", "L1", "L2"])
    gain.add_argument("--to-resolution", choices=["L0", "L1", "L2"], required=True)
    gain.add_argument(
        "--weight",
        action="append",
        default=[],
        help="declared cost weight as meter=value",
    )

    cost_put = sub.add_parser(
        "cost-model-put", help="register one immutable versioned cost model"
    )
    cost_put.add_argument("cost_model_id")
    cost_put.add_argument("--version", type=int, required=True)
    cost_put.add_argument(
        "--weight", action="append", default=[], required=True, help="meter=value"
    )
    cost_put.add_argument("--description", default="")

    sub.add_parser("cost-model-list", help="list registered cost models")

    policy_create = sub.add_parser(
        "policy-create", help="create an information-resolution policy candidate"
    )
    policy_create.add_argument("--candidate-id")
    policy_create.add_argument("--mode", choices=["rule", "fixed"], required=True)
    policy_create.add_argument("--resolution", choices=["L0", "L1", "L2"])
    policy_create.add_argument("--change", action="append", default=[], required=True)

    policy_eval = sub.add_parser(
        "policy-evaluate",
        help="run baseline/candidate eval and attach calibration evidence",
    )
    policy_eval.add_argument("candidate_id")
    policy_eval.add_argument("--suite", default="evals/foundation-v4.json")
    policy_eval.add_argument("--cost-model-id")
    policy_eval.add_argument("--min-pairs", type=int, default=1)

    policy_promote = sub.add_parser(
        "policy-promote", help="explicitly promote an eligible policy for future turns"
    )
    policy_promote.add_argument("candidate_id")

    policy_rollback = sub.add_parser(
        "policy-rollback",
        help="rollback active information-resolution policy for future turns",
    )
    policy_rollback.add_argument("--reason", default="explicit rollback")

    sub.add_parser(
        "policy-status", help="show active policy, candidates and promotion history"
    )

    web = sub.add_parser("web", help="start the local Myth Agent workspace")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-browser", action="store_true")

    worker = sub.add_parser(
        "worker",
        help="run the standalone durable executor for admitted/recoverable work",
    )
    worker.add_argument("--poll-seconds", type=float, default=2.0)
    worker.add_argument("--max-active", type=int, default=4)
    return parser


# 按明确配置装配供应商适配器；不读取其他应用认证文件。
def _provider(args: argparse.Namespace):
    return create_provider(
        args.provider,
        ollama_base_url=args.ollama_url,
        runtime_root=args.root,
    )


# 检查连接状态，不可用时提前拒绝新工作；检查不是请求成功或语义验收。
def _require_provider(args: argparse.Namespace):
    provider = _provider(args)
    status = provider.check()
    if not status.ready:
        raise SystemExit(
            "provider is not ready: "
            + json.dumps(status.details or {}, ensure_ascii=False)
        )
    return provider


# 分派明确 CLI 命令到用例并输出状态；固定任务失败保留报告且返回非零，不自动发布策略。
def main() -> None:
    # 每个分支只装配实际命令所需能力；Eval 记录不自动发布，显式 promote 才能切换策略。
    args = build_parser().parse_args()

    if args.command == "task-benchmark":
        from .task_benchmark import run_task_benchmark

        result = run_task_benchmark(
            args.suite,
            args.output,
            provider_name=args.provider,
            model=args.model,
            ollama_url=args.ollama_url,
            repeats=args.repeats,
            auth_root=args.root,
            arms=tuple(args.arm or ["myth", "simple-loop"]),
            case_ids=args.case_ids,
            on_trial=lambda trial: print(
                f"{trial['repeat']} {trial['case_id']} {trial['arm']}: "
                f"{'PASS' if trial['success'] else 'FAIL'} ({trial['status']})",
                flush=True,
            ),
        )
        _print(
            {
                "report": str(args.output.resolve() / "report.json"),
                "complete_suite": result["complete_suite"],
                "summary": result["summary"],
            }
        )
        if any(not t["success"] for t in result["trials"]):
            raise SystemExit(1)
        return

    if args.command == "provider-check":
        _print(_provider(args).check())
        return
    if args.command == "auth-login":
        from .auth import ChatGPTAuthManager, run_loopback_login

        status = run_loopback_login(
            ChatGPTAuthManager(args.root),
            profile_id=args.profile_id,
            open_browser=not args.no_browser,
        )
        _print(status.serializable())
        return
    if args.command == "auth-status":
        from .auth import ChatGPTAuthManager

        manager = ChatGPTAuthManager(args.root)
        _print(
            {"status": manager.status().serializable(), "profiles": manager.profiles()}
        )
        return
    if args.command == "auth-logout":
        from .auth import ChatGPTAuthManager

        _print(ChatGPTAuthManager(args.root).logout(args.profile_id))
        return
    if args.command == "eval":
        from .evaluation_runner import run_eval_suite

        result = run_eval_suite(
            args.suite,
            args.case_ids,
            policy_id=args.policy_id,
            resolution_policy=args.resolution_policy,
        )
        if args.record:
            from .platform.evaluation_store import SqliteEvaluationLedger

            with MythRuntime(args.root) as runtime:
                saved = SqliteEvaluationLedger(runtime).record(
                    result, policy_id=args.policy_id
                )
            result["recorded_eval_run_id"] = saved["eval_run_id"]
        _print(result)
        return
    if args.command == "eval-history":
        from .platform.evaluation_store import SqliteEvaluationLedger

        with MythRuntime(args.root) as runtime:
            _print(SqliteEvaluationLedger(runtime).list_runs(args.limit))
        return
    if args.command == "eval-compare":
        from .platform.evaluation_store import SqliteEvaluationLedger

        with MythRuntime(args.root) as runtime:
            _print(
                SqliteEvaluationLedger(runtime).compare(
                    args.baseline_eval_run_id,
                    args.candidate_eval_run_id,
                )
            )
        return
    if args.command == "gain":
        from .domains.information import InformationResolution
        from .platform.evaluation_store import SqliteEvaluationLedger
        from .strategies import PairedEvalGainEstimator

        weights = _weights(args.weight)
        with MythRuntime(args.root) as runtime:
            pairs = SqliteEvaluationLedger(runtime).paired_comparisons(
                args.baseline_eval_run_id,
                args.candidate_eval_run_id,
            )
        pair = next((item for item in pairs if item.case_id == args.case_id), None)
        if pair is None:
            raise SystemExit("case_id is not present in both evaluation runs")
        source_ref = args.source_ref or (
            pair.evidence_refs[0] if pair.evidence_refs else f"eval:{pair.case_id}"
        )
        estimate = PairedEvalGainEstimator().estimate(
            pair,
            source_ref=source_ref,
            from_resolution=(
                InformationResolution(args.from_resolution)
                if args.from_resolution
                else None
            ),
            to_resolution=InformationResolution(args.to_resolution),
            cost_weights=weights or None,
        )
        _print(estimate.serializable())
        return
    if args.command == "cost-model-put":
        from .platform.cost_model import CostModel, SqliteCostModelRegistry

        model = CostModel(
            args.cost_model_id,
            args.version,
            _weights(args.weight),
            args.description,
        )
        with MythRuntime(args.root) as runtime:
            _print(SqliteCostModelRegistry(runtime).put(model))
        return
    if args.command == "cost-model-list":
        from .platform.cost_model import SqliteCostModelRegistry

        with MythRuntime(args.root) as runtime:
            _print(SqliteCostModelRegistry(runtime).list())
        return
    if args.command == "policy-create":
        from .platform.evolution_store import SqliteEvolutionControl

        config = {"mode": args.mode}
        if args.mode == "fixed":
            if not args.resolution:
                raise SystemExit("--resolution is required for fixed policy")
            config["resolution"] = args.resolution
        elif args.resolution:
            raise SystemExit("--resolution only applies to fixed policy")
        with MythRuntime(args.root) as runtime:
            _print(
                SqliteEvolutionControl(runtime).create_candidate(
                    config=config,
                    changes=args.change,
                    candidate_id=args.candidate_id,
                )
            )
        return
    if args.command == "policy-evaluate":
        from .evaluation_runner import run_eval_suite
        from .platform.evaluation_store import SqliteEvaluationLedger
        from .platform.evolution_store import SqliteEvolutionControl

        with MythRuntime(args.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            candidate = evolution.candidate(args.candidate_id)
            baseline = evolution.policy(candidate["baseline_policy_id"])
        baseline_result = run_eval_suite(
            args.suite,
            policy_id=baseline["policy_id"],
            policy_config=baseline["config"],
        )
        candidate_result = run_eval_suite(
            args.suite,
            policy_id=candidate["candidate_id"],
            policy_config=candidate["config"],
        )
        with MythRuntime(args.root) as runtime:
            ledger = SqliteEvaluationLedger(runtime)
            baseline_saved = ledger.record(
                baseline_result, policy_id=baseline["policy_id"]
            )
            candidate_saved = ledger.record(
                candidate_result, policy_id=candidate["candidate_id"]
            )
            value = SqliteEvolutionControl(runtime).attach_evaluation(
                candidate["candidate_id"],
                baseline_eval_run_id=baseline_saved["eval_run_id"],
                candidate_eval_run_id=candidate_saved["eval_run_id"],
                cost_model_id=args.cost_model_id,
                min_pairs=args.min_pairs,
            )
        _print(value)
        return
    if args.command == "policy-promote":
        from .platform.evolution_store import SqliteEvolutionControl

        with MythRuntime(args.root) as runtime:
            _print(SqliteEvolutionControl(runtime).promote(args.candidate_id))
        return
    if args.command == "policy-rollback":
        from .platform.evolution_store import SqliteEvolutionControl

        with MythRuntime(args.root) as runtime:
            _print(SqliteEvolutionControl(runtime).rollback(reason=args.reason))
        return
    if args.command == "policy-status":
        from .platform.evolution_store import SqliteEvolutionControl

        with MythRuntime(args.root) as runtime:
            evolution = SqliteEvolutionControl(runtime)
            value = evolution.status()
            value["candidates"] = evolution.candidates()
            _print(value)
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
    if args.command == "worker":
        from .durable_executor import DurableExecutor

        raise SystemExit(
            DurableExecutor(
                args.root,
                poll_seconds=args.poll_seconds,
                max_active=args.max_active,
            ).serve_forever()
        )

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
                acceptance=(
                    json.loads(args.acceptance.read_text(encoding="utf-8"))
                    if args.acceptance
                    else None
                ),
            )
            _print(agent.run(run_id, provider))
        elif args.command == "continue-agent":
            _print(AgentRuntime(runtime).run(args.run_id, _require_provider(args)))
        elif args.command == "answer-agent":
            _print(
                AgentRuntime(runtime).resume(
                    args.run_id,
                    _require_provider(args),
                    args.text,
                    question_id=args.question_id,
                )
            )
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
