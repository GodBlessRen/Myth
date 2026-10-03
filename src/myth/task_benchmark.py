"""固定日常任务的真实 Workspace 运行器与独立小型 oracle。
两组共用持久运行时，只消融路由；逐次保留失败、字节验收、调用量和证据目录，脚本替身始终单独标识。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
import uuid

from .artifacts import atomic_write
from .domain import canonical_json, digest_json
from .domains.information import IntentPick, IntentRoute
from .models import ModelResult
from .providers import create_provider
from .runtime import MythRuntime
from .workspace import Workspace


# 路由消融策略；所有任务选择 Agent，其他 Runtime、工具和预算保持相同。
class SimpleLoopPicker:
    # 从输入与已给上下文选择处理路径；输出是路由提案，具体准入与效果仍由 Runtime 控制。
    def pick(self, value, context):
        return IntentPick(IntentRoute.AGENT, reason="simple-loop routing ablation")


# 固定任务运行器替身；固定动作只检验编排和 oracle，provider_id 兼容传输合同而非真实 Ollama 调用。
class FixtureProvider:
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id = "ollama"

    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self, steps):
        # steps：固定工作流节点序列；实际完成集合另行管理。
        self.steps = iter(steps)

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, request):
        step = next(self.steps, {"claim": "Fixture exhausted"})
        value = {
            "decision_type": "tool_call" if "tool" in step else "request_completion",
            "reason": "fixed harness fixture",
            "capability_id": step.get("tool", ""),
            "arguments_json": json.dumps(step.get("args", {}), ensure_ascii=False),
            "question": "",
            "missing_info_category": "",
            "claim": step.get("claim", ""),
            "goal_coverage": "answer",
            "evidence_refs": [],
            "remaining": [],
        }
        return ModelResult(
            json.dumps(value, ensure_ascii=False),
            {"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            {"fixture": True},
        )


def check_acceptance(workspace, turn, case):
    """独立读取真实工具结果、对象字节及原文件；固定 token 检查只覆盖小范围，不把模型 claim 当产物证明。"""
    oracle = case["acceptance"]
    session = workspace.repository.session(turn["session_id"])
    answers = [
        m["content"]
        for m in session["messages"]
        if m["run_id"] == turn["run_id"] and m["role"] == "assistant"
    ]
    answer = answers[-1] if answers else ""
    results = [a.get("result") or {} for a in turn["activities"]]
    artifacts = {
        r["artifact"]["name"]: r["artifact"] for r in results if "artifact" in r
    }
    checks = {"completed": turn["status"] == "COMPLETED"}
    for token in oracle.get("answer_contains", []):
        checks[f"answer:{token}"] = token in answer
    for capability in oracle.get("tools", []):
        checks[f"tool:{capability}"] = any(
            r.get("capability_id") == capability for r in results
        )
    for name, expected in oracle.get("artifacts", {}).items():
        artifact = artifacts.get(name)
        checks[f"artifact:{name}"] = bool(
            artifact
            and workspace.repository.runtime.objects.get(artifact["digest"])
            == expected.encode("utf-8")
        )
    project = turn["snapshot"].get("project")
    for name, expected in case.get("files", {}).items():
        checks[f"original:{name}"] = (
            Path(project["root"]) / name
        ).read_bytes() == expected.encode("utf-8")
    return checks, answer, list(artifacts.values())


# 在独立持久 root 执行固定任务，并实际重开 Goal 数据库；记录所有 Run、状态、计量与独立 checks。
def _trial(root, case, arm, settings, provider):
    started = time.perf_counter()
    with MythRuntime(root) as runtime:
        workspace = Workspace(
            runtime, intent_picker=SimpleLoopPicker() if arm == "simple-loop" else None
        )
        repo = workspace.repository
        repo.save_settings(settings)
        project_root = root / "project"
        project_root.mkdir()
        for name, content in case.get("files", {}).items():
            path = (project_root / name).resolve()
            if not path.is_relative_to(project_root.resolve()):
                raise ValueError("fixture path escapes project")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        project = repo.create_project({"name": case["id"], "root": str(project_root)})
        for doc in case.get("documents", []):
            repo.import_document({**doc, "project_id": project["id"]})
        goal = (
            workspace.personal.create_goal("Fixed continuity task")
            if case.get("first_prompt")
            else None
        )

        # 每次试次在独立 Session 正常准入；Goal link 已由 create_turn 的共同事务保存。
        def admit(prompt):
            sid = repo.create_session(project_id=project["id"])["id"]
            context = workspace.personal.goal_view(goal["goal_id"]) if goal else None
            turn = repo.create_turn(
                sid,
                prompt,
                uuid.uuid4().hex,
                goal_id=goal["goal_id"] if goal else None,
                goal_context=context,
            )
            workspace.control.ensure(turn["run_id"], turn["settings"])
            return turn["run_id"]

        run_ids = []
        prerequisite_ok = True
        if goal:
            first = admit(case["first_prompt"])
            run_ids.append(first)
            workspace.run(first, provider)
            prerequisite_ok = repo.turn(first)["status"] == "COMPLETED"
            # 真实关闭并重开数据库；跨会话连续性不能只靠内存对象证明。
            runtime.close()
            runtime = MythRuntime(root)
            workspace = Workspace(
                runtime,
                intent_picker=SimpleLoopPicker() if arm == "simple-loop" else None,
            )
            repo = workspace.repository
        try:
            rid = admit(case["prompt"]) if prerequisite_ok else first
            if prerequisite_ok:
                run_ids.append(rid)
            if case.get("interrupt_before_run"):
                repo.interrupt(
                    rid, "benchmark: driver stopped before external dispatch"
                )
            if prerequisite_ok:
                workspace.run(rid, provider)
            turn = repo.turn(rid)
            checks, answer, artifacts = check_acceptance(workspace, turn, case)
            checks["prerequisite"] = prerequisite_ok
            model_facts = [
                m
                for r in run_ids
                for m in repo.decisions.status(r)["model_invocations"]
            ]
            turns = [repo.turn(r) for r in run_ids]
            usage = Counter()
            context = Counter()
            signatures = []
            for model in model_facts:
                usage.update(model.get("usage") or {})
                request = json.loads(runtime.objects.get(model["request_ref"]))
                report = request.get("context_report") or {}
                for key in ("selected", "folded", "dropped"):
                    value = report.get(key, [])
                    context[key] += (
                        len(value) if isinstance(value, list) else int(value or 0)
                    )
            for t in turns:
                for activity in t["activities"]:
                    decision = activity.get("decision") or {}
                    if decision.get("decision_type") == "tool_call":
                        signatures.append(
                            canonical_json(
                                [
                                    decision.get("capability_id"),
                                    decision.get("arguments"),
                                ]
                            )
                        )
            success = all(checks.values())
            errors = [
                a["result"]["error"]
                for a in turn["activities"]
                if (a.get("result") or {}).get("error")
            ]
            return {
                "case_id": case["id"],
                "category": case["category"],
                "arm": arm,
                "run_ids": run_ids,
                "status": turn["status"],
                "success": success,
                "checks": checks,
                "answer": answer,
                "artifacts": artifacts,
                "failure_taxonomy": (
                    None
                    if success
                    else (
                        "runtime"
                        if turn["status"] in {"UNKNOWN", "INTERRUPTED", "FAILED"}
                        else "tool" if errors else "model_or_context"
                    )
                ),
                "errors": errors,
                "turn_error": turn.get("error"),
                "human_takeover": turn["status"]
                in {"WAITING_USER", "UNKNOWN", "INTERRUPTED", "BUDGET_EXHAUSTED"},
                "completion_without_acceptance": turn["status"] == "COMPLETED"
                and not success,
                "recovery_success": (
                    success if case.get("interrupt_before_run") else None
                ),
                "unknown_reconcile_success": None,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "model_calls": len(model_facts),
                "usage": dict(usage),
                "tool_calls": len(signatures),
                "repeated_tool_calls": sum(n - 1 for n in Counter(signatures).values()),
                "context": dict(context),
                "evidence_root": str(root / ".runtime"),
            }
        finally:
            runtime.close()


# 校验固定题身份及新证据目录，逐题逐次保存成功/失败；完整分母不随筛选或 runner exception 消失。
def run_task_benchmark(
    suite_path,
    output,
    *,
    provider_name="scripted",
    model="fixture",
    ollama_url="http://127.0.0.1:11434",
    repeats=3,
    arms=("myth", "simple-loop"),
    case_ids=(),
    on_trial=None,
    auth_root=".",
):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be 1-10")
    if (
        not arms
        or len(set(arms)) != len(arms)
        or any(a not in {"myth", "simple-loop"} for a in arms)
    ):
        raise ValueError("arms must be myth and/or simple-loop without duplicates")
    suite = json.loads(Path(suite_path).read_text(encoding="utf-8"))
    cases = suite["cases"]
    ids = [c["id"] for c in cases]
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(
            not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}", ident) for ident in ids
        )
    ):
        raise ValueError("case ids must be unique and nonempty")
    if set(case_ids) - set(ids):
        raise ValueError("unknown case id")
    selected = [c for c in cases if not case_ids or c["id"] in case_ids]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    settings = {
        "provider": "ollama" if provider_name == "scripted" else provider_name,
        "model": model,
        "ollama_url": ollama_url,
        "max_steps": 6,
        "max_output_tokens": 512,
        "num_ctx": 8192,
        "temperature": 0.0,
        "thinking": False,
    }
    report = {
        "suite_id": suite["suite_id"],
        "suite_digest": digest_json(suite),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider_name,
        "model": model,
        "settings": settings,
        "repeats": repeats,
        "arms": list(arms),
        "kind": "harness_fixture" if provider_name == "scripted" else "real_provider",
        "oracle_scope": "exact artifact bytes, required tools, answer tokens, unchanged originals; no broad semantic score",
        "comparison": "intent routing ablation; same durable runtime and tools",
        "complete_suite": False,
        "planned_trials": len(cases) * repeats * len(arms),
        "trials": [],
    }
    from . import __version__

    source_root = Path(__file__).parent
    report["runtime_version"] = __version__
    report["source_digest"] = digest_json(
        {
            p.relative_to(source_root)
            .as_posix(): p.read_text(encoding="utf-8")
            .replace("\r\n", "\n")
            for p in sorted(source_root.rglob("*.py"))
        }
    )
    report["suite_case_count"] = len(cases)
    report["selected_case_count"] = len(selected)
    report["model_metadata"] = None
    if provider_name == "ollama":
        try:
            metadata_provider = create_provider("ollama", ollama_base_url=ollama_url)
            tags = metadata_provider._json_request("GET", "/api/tags")
            item = next(
                (m for m in tags.get("models", []) if m.get("name") == model), {}
            )
            report["model_metadata"] = {
                key: item[key]
                for key in ("name", "digest", "size", "details", "modified_at")
                if key in item
            }
        except (RuntimeError, ValueError):
            report["model_metadata_error"] = "model metadata not measured"
    atomic_write(
        output / "suite.json",
        json.dumps(suite, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    path = output / "report.json"

    # 原子保存增量报告及分组汇总；进程中断仍可读取此前试次，未知计量保持未测量标记。
    def save():
        trials = report["trials"]
        report["summary"] = {
            arm: {
                "trials": len(group := [t for t in trials if t["arm"] == arm]),
                "passed": sum(t["success"] for t in group),
                "completion_without_acceptance": sum(
                    t["completion_without_acceptance"] for t in group
                ),
                "human_takeover": sum(t["human_takeover"] for t in group),
                "model_calls": sum(t["model_calls"] or 0 for t in group),
                "model_calls_not_measured": sum(
                    t["model_calls"] is None for t in group
                ),
            }
            for arm in arms
        }
        atomic_write(
            path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        )

    save()
    for repeat in range(1, repeats + 1):
        for case in selected:
            for arm in arms:
                provider = (
                    FixtureProvider(case["steps"])
                    if provider_name == "scripted"
                    else create_provider(
                        provider_name,
                        ollama_base_url=ollama_url,
                        runtime_root=str(auth_root),
                    )
                )
                trial_root = output / f"{repeat}-{case['id']}-{arm}"
                try:
                    trial = _trial(trial_root, case, arm, settings, provider)
                except Exception as exc:
                    # 前置条件、夹具或 Runner 失败仍计入完整分母；中断前已保存的增量报告继续保留。
                    trial = {
                        "case_id": case["id"],
                        "category": case["category"],
                        "arm": arm,
                        "success": False,
                        "status": "RUNNER_ERROR",
                        "failure_taxonomy": "runner",
                        "checks": {"runner": False},
                        "errors": [f"{type(exc).__name__}: {exc}"],
                        "human_takeover": True,
                        "completion_without_acceptance": False,
                        "model_calls": None,
                        "evidence_root": str(trial_root / ".runtime"),
                    }
                trial["repeat"] = repeat
                report["trials"].append(trial)
                save()
                if on_trial:
                    on_trial(trial)
    report["complete_suite"] = len(report["trials"]) == report["planned_trials"]
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    return report
