"""固定日常任务的真实 Workspace 运行器与独立小型 oracle。
两组共用持久运行时，只消融路由；逐次保留失败、字节验收、调用量和证据目录，脚本替身始终单独标识。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from math import sqrt
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
from .session_statistics import usage_measurements
from .workspace import Workspace


# 四种 Context 受控组保留同一组基础 Harness 能力，只消融因果和相关性。
# 命名属于 disposable Benchmark，不进入产品设置或授予新的执行许可。
_COMMON_CONTEXT_MECHANISMS = (
    "action_fusion", "context_compaction", "observation_recall",
)
CONTEXT_BENCHMARK_ARMS = {
    "context-baseline": _COMMON_CONTEXT_MECHANISMS,
    "context-causal": _COMMON_CONTEXT_MECHANISMS + ("context_causal_guard",),
    "context-relevance": _COMMON_CONTEXT_MECHANISMS + ("context_relevance_ranking",),
    "context-full": _COMMON_CONTEXT_MECHANISMS
    + ("context_causal_guard", "context_relevance_ranking"),
}


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


# 计算固定比例的 Wilson 95% 区间；只描述当前完成 case 的采样不确定性，不把缺测补成成功或失败。
def _wilson_95(successes, total):
    if total <= 0:
        return None
    z = 1.959963984540054
    rate = successes / total
    denominator = 1.0 + (z * z / total)
    center = (rate + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


# 汇总一个 benchmark arm 的重复试次；pass@k 表示至少成功一次，pass^k 表示同 case 的 k 次全部成功。
def _arm_summary(trials, arm, case_ids, repeats):
    group = [trial for trial in trials if trial["arm"] == arm]
    grouped = {case_id: [] for case_id in case_ids}
    for trial in group:
        case_id = trial.get("case_id")
        if case_id in grouped:
            grouped[case_id].append(trial)

    complete_cases = [
        case_id for case_id in case_ids if len(grouped[case_id]) == repeats
    ]
    incomplete_cases = [
        case_id for case_id in case_ids if len(grouped[case_id]) != repeats
    ]
    successes = {
        case_id: sum(bool(trial.get("success")) for trial in grouped[case_id])
        for case_id in complete_cases
    }
    capability_cases = [case_id for case_id in complete_cases if successes[case_id] > 0]
    reliable_cases = [
        case_id for case_id in complete_cases if successes[case_id] == repeats
    ]
    mixed_cases = [
        case_id for case_id in complete_cases if 0 < successes[case_id] < repeats
    ]
    failed_cases = [case_id for case_id in complete_cases if successes[case_id] == 0]

    passed = sum(bool(trial.get("success")) for trial in group)
    model_calls_not_measured = sum(trial.get("model_calls") is None for trial in group)
    model_calls = sum(
        int(trial.get("model_calls") or 0)
        for trial in group
        if trial.get("model_calls") is not None
    )
    failure_taxonomy = Counter(
        trial.get("failure_taxonomy")
        for trial in group
        if not trial.get("success") and trial.get("failure_taxonomy")
    )
    complete_count = len(complete_cases)
    return {
        "trials": len(group),
        "passed": passed,
        "trial_pass_rate": (passed / len(group)) if group else None,
        "completion_without_acceptance": sum(
            trial.get("completion_without_acceptance", False) for trial in group
        ),
        "human_takeover": sum(trial.get("human_takeover", False) for trial in group),
        "model_calls": model_calls,
        "model_calls_not_measured": model_calls_not_measured,
        "model_calls_per_success": (
            None
            if passed == 0 or model_calls_not_measured
            else model_calls / passed
        ),
        "failure_taxonomy": dict(sorted(failure_taxonomy.items())),
        "k": repeats,
        "complete_case_count": complete_count,
        "incomplete_cases": incomplete_cases,
        "pass_at_k_cases": len(capability_cases),
        "pass_at_k": (
            len(capability_cases) / complete_count if complete_count else None
        ),
        "pass_at_k_ci95": _wilson_95(len(capability_cases), complete_count),
        "pass_pow_k_cases": len(reliable_cases),
        "pass_pow_k": len(reliable_cases) / complete_count if complete_count else None,
        "pass_pow_k_ci95": _wilson_95(len(reliable_cases), complete_count),
        "mixed_outcome_cases": mixed_cases,
        "all_failed_cases": failed_cases,
    }


# 只能比较同 case/repeat 的真实试次；缺测成本和不完整变体绝不补零以制造效率收益。
def summarize_context_ablation(trials, arms, case_ids, repeats, *, kind, complete_suite):
    """Context 机制配对汇总：质量、安全、成本分离；输出不是自动 Promote 决定。"""
    expected = frozenset(CONTEXT_BENCHMARK_ARMS)
    variants_complete = frozenset(arms) == expected
    by_block = {}
    duplicate = []
    for trial in trials:
        key = (trial.get("case_id"), trial.get("repeat"))
        arm = trial.get("arm")
        group = by_block.setdefault(key, {})
        if arm in group:
            duplicate.append({"case_id": key[0], "repeat": key[1], "arm": arm})
        group[arm] = trial

    pairs = []
    quality = Counter()
    safety = Counter()
    metric_names = ("input_tokens", "output_tokens", "provider_wall_ms")
    cost = {
        name: {"paired_samples": 0, "baseline_sum": 0, "full_sum": 0}
        for name in metric_names
    }
    expected_blocks = len(case_ids) * repeats
    for case_id in case_ids:
        for repeat in range(1, repeats + 1):
            group = by_block.get((case_id, repeat)) or {}
            if not variants_complete or set(group) != expected:
                pairs.append({
                    "case_id": case_id, "repeat": repeat,
                    "status": "INCOMPLETE", "observed_arms": sorted(group),
                })
                continue
            baseline, full = group["context-baseline"], group["context-full"]
            b_ok, f_ok = baseline.get("success") is True, full.get("success") is True
            outcome = (
                "improved" if f_ok and not b_ok else
                "regressed" if b_ok and not f_ok else
                "both_pass" if b_ok else "both_fail"
            )
            quality[outcome] += 1
            base_unknown = baseline.get("status") == "UNKNOWN"
            full_unknown = full.get("status") == "UNKNOWN"
            if full_unknown and not base_unknown:
                safety["new_unknown"] += 1
            if full.get("human_takeover") is True and baseline.get("human_takeover") is False:
                safety["new_human_takeover"] += 1
            repeats_base = baseline.get("repeated_tool_calls")
            repeats_full = full.get("repeated_tool_calls")
            if (
                type(repeats_base) is int and type(repeats_full) is int
                and repeats_full > repeats_base
            ):
                safety["more_repeated_tool_calls"] += 1

            metrics = {}
            for name in metric_names:
                a = (baseline.get("usage_measured") or {}).get(name)
                b = (full.get("usage_measured") or {}).get(name)
                valid = (
                    type(a) in (int, float) and type(b) in (int, float)
                    and a >= 0 and b >= 0
                )
                metrics[name] = {
                    "baseline": a if valid else None,
                    "full": b if valid else None,
                    "delta": b - a if valid else None,
                }
                if valid:
                    cost[name]["paired_samples"] += 1
                    cost[name]["baseline_sum"] += a
                    cost[name]["full_sum"] += b
            # 机制 on/off 必须出现在真正冻结的请求报告中；没有模型调用记缺测，而非假触发。
            activation = {}
            for arm in sorted(expected):
                records = group[arm].get("context_activation")
                if not isinstance(records, list) or not records:
                    activation[arm] = None
                    continue
                want_causal = arm in {"context-causal", "context-full"}
                want_relevance = arm in {"context-relevance", "context-full"}
                activation[arm] = all(
                    isinstance(item, dict)
                    and (item.get("causality") != "disabled-for-controlled-evaluation") == want_causal
                    and (item.get("relevance") != "disabled-for-controlled-evaluation") == want_relevance
                    for item in records
                )
            pairs.append({
                "case_id": case_id,
                "repeat": repeat,
                "status": "PAIRED",
                "quality": {
                    "baseline_pass": b_ok,
                    "full_pass": f_ok,
                    "causal_only_pass": group["context-causal"].get("success") is True,
                    "relevance_only_pass": group["context-relevance"].get("success") is True,
                    "outcome_flip": outcome,
                },
                "safety": {
                    "new_unknown": full_unknown and not base_unknown,
                    "new_human_takeover": (
                        full.get("human_takeover") is True
                        and baseline.get("human_takeover") is False
                    ),
                },
                "measured_cost": metrics,
                "mechanism_config_verified_in_requests": activation,
                "harness_evidence": {
                    arm: {
                        "run_ids": group[arm].get("run_ids"),
                        "status": group[arm].get("status"),
                        "evidence_root": group[arm].get("evidence_root"),
                    }
                    for arm in sorted(expected)
                },
            })

    complete_pairs = sum(item["status"] == "PAIRED" for item in pairs)
    cost_summary = {}
    for name, item in cost.items():
        complete_metric = (
            complete_suite and variants_complete
            and complete_pairs == expected_blocks
            and item["paired_samples"] == expected_blocks
        )
        cost_summary[name] = {
            "paired_samples": item["paired_samples"],
            "expected_pairs": expected_blocks,
            "baseline_total": item["baseline_sum"] if complete_metric else None,
            "full_total": item["full_sum"] if complete_metric else None,
            "delta": (
                item["full_sum"] - item["baseline_sum"] if complete_metric else None
            ),
        }
    deltas = [item["delta"] for item in cost_summary.values()]
    evidence_full = complete_suite and variants_complete and complete_pairs == expected_blocks
    metrics_full = evidence_full and all(x is not None for x in deltas)
    no_quality_regression = quality["regressed"] == 0
    # 固定小型 Oracle 集若本身未被候选完整完成，即使双方都失败、成本下降也非晋级。
    full_oracle_floor = (
        expected_blocks > 0 and quality["both_pass"] + quality["improved"] == expected_blocks
    )
    no_safety_regression = (
        safety["new_unknown"] == 0
        and safety["new_human_takeover"] == 0
        and safety["more_repeated_tool_calls"] == 0
    )
    activation_mismatch = sum(
        any(value is False for value in (pair.get("mechanism_config_verified_in_requests") or {}).values())
        for pair in pairs if pair["status"] == "PAIRED"
    )
    # 四种 Arm 都要有真实可归属的模型机会/计量；只核对 baseline/full 会漏掉
    # causal-only 或 relevance-only 的 Runner ERROR，从而误报可晋级。
    variant_measurement_pairs = 0
    context_activation_pairs = 0
    for case_id in case_ids:
        for repeat in range(1, repeats + 1):
            group = by_block.get((case_id, repeat)) or {}
            if set(group) != expected:
                continue
            valid = all(
                trial.get("status") != "RUNNER_ERROR"
                and type(trial.get("model_calls")) is int
                and trial["model_calls"] >= 0
                and all(
                    type((trial.get("usage_measured") or {}).get(meter)) is int
                    and trial["usage_measured"][meter] >= 0
                    for meter in metric_names
                )
                and (
                    trial["model_calls"] == 0
                    or isinstance(trial.get("context_activation"), list)
                    and len(trial["context_activation"]) == trial["model_calls"]
                )
                for trial in group.values()
            )
            if valid:
                variant_measurement_pairs += 1
                if any(group[arm]["model_calls"] > 0 for arm in expected):
                    context_activation_pairs += 1
    ready = (
        kind == "real_provider"
        and evidence_full and metrics_full and no_quality_regression
        and full_oracle_floor and no_safety_regression and activation_mismatch == 0
        and variant_measurement_pairs == expected_blocks
        and context_activation_pairs > 0
        and all(delta <= 0 for delta in deltas)
        and any(delta < 0 for delta in deltas)
    )
    return {
        "method": "same-case-repeat-controlled-harness-v1",
        "complete_pair_count": complete_pairs,
        "expected_pair_count": expected_blocks,
        "full_context_arms": variants_complete,
        "quality": dict(sorted(quality.items())),
        "all_full_arm_oracles_pass": full_oracle_floor,
        "safety": dict(sorted(safety.items())),
        "cost": cost_summary,
        "activation_mismatch_count": activation_mismatch,
        "fully_measured_variant_pairs": variant_measurement_pairs,
        "context_activation_pairs": context_activation_pairs,
        "pairs": pairs,
        "ready_for_separate_heldout_review": ready,
        "promotion_eligible": False,
        "release_policy": (
            "No automatic promotion; heldout identity, repeated model quality, full "
            "provider receipts and human approval required. Mechanism interaction "
            "is observable, not causal proof."
        ),
        "evidence_kind": kind,
    }


# 在独立持久 root 执行固定任务，并实际重开 Goal 数据库；记录所有 Run、状态、计量与独立 checks。
def _trial(root, case, arm, settings, provider, *, context_mechanisms=None):
    started = time.perf_counter()
    with MythRuntime(root) as runtime:
        workspace = Workspace(
            runtime,
            intent_picker=SimpleLoopPicker() if arm == "simple-loop" else None,
            evaluation_harness_mechanisms=context_mechanisms,
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
            repo.knowledge.import_document({**doc, "project_id": project["id"]})
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
            workspace.control.ensure(turn["run_id"])
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
                evaluation_harness_mechanisms=context_mechanisms,
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
            # 原始 usage 保持旧报告兼容，但新比较只能使用所有 Attempt 均实测的字段。
            measurement = usage_measurements(
                model_facts,
                ("input_tokens", "output_tokens", "cached_input_tokens", "provider_wall_ms"),
            )
            context_bytes = serialized_request_bytes = 0
            context_activation = []
            signatures = []
            for model in model_facts:
                usage.update(model.get("usage") or {})
                raw_request = runtime.objects.get(model["request_ref"])
                request = json.loads(raw_request)
                report = request.get("context_report") or {}
                context_bytes += int(report.get("bytes_used") or 0)
                serialized_request_bytes += len(raw_request)
                for key in ("selected", "folded", "dropped"):
                    value = report.get(key, [])
                    context[key] += (
                        len(value) if isinstance(value, list) else int(value or 0)
                    )
                governance = report.get("governance") or {}
                context_activation.append({
                    "model_attempt_id": model["model_attempt_id"],
                    "causality": governance.get("causality"),
                    "relevance": governance.get("relevance"),
                    "context_mode": report.get("context_mode"),
                    "selected": len(report.get("selected") or []),
                    "bytes_used": report.get("bytes_used"),
                })
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
                "usage_measured": measurement["totals"],
                "usage_samples": measurement["samples"],
                "measured_model_attempts": measurement["attempts"],
                "context_bytes": context_bytes,
                "serialized_request_bytes": serialized_request_bytes,
                "harness_mechanisms": list(context_mechanisms) if context_mechanisms is not None else None,
                "context_activation": context_activation,
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
        or any(a not in {"myth", "simple-loop", *CONTEXT_BENCHMARK_ARMS} for a in arms)
    ):
        raise ValueError("unknown or duplicate benchmark arm")
    if any(arm in CONTEXT_BENCHMARK_ARMS for arm in arms) and any(
        arm not in CONTEXT_BENCHMARK_ARMS for arm in arms
    ):
        raise ValueError("context ablation cannot mix with routing arms")
    suite = json.loads(Path(suite_path).read_text(encoding="utf-8"))
    cases = suite["cases"]
    partition = suite.get("partition", "discovery")
    if partition not in {"discovery", "heldout"}:
        raise ValueError("suite partition must be discovery or heldout")
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
        "partition": "declared_heldout" if partition == "heldout" else "discovery",
        "oracle_scope": "exact artifact bytes, required tools, answer tokens, unchanged originals; no broad semantic score",
        "comparison": (
            "context causal/relevance controlled ablation; same frozen base mechanisms and durable Runtime"
            if all(arm in CONTEXT_BENCHMARK_ARMS for arm in arms)
            else "intent routing ablation; same durable runtime and tools"
        ),
        "harness_mechanisms": {
            arm: list(CONTEXT_BENCHMARK_ARMS[arm])
            for arm in arms if arm in CONTEXT_BENCHMARK_ARMS
        },
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

    selected_case_ids = tuple(case["id"] for case in selected)

    # 原子保存增量报告及分组汇总；未完成 k 次的 case 保持 incomplete，不能提前伪装 pass^k。
    def save():
        trials = report["trials"]
        report["summary"] = {
            arm: _arm_summary(trials, arm, selected_case_ids, repeats) for arm in arms
        }
        if all(arm in CONTEXT_BENCHMARK_ARMS for arm in arms):
            report["context_ablation"] = summarize_context_ablation(
                trials, arms, selected_case_ids, repeats,
                kind=report["kind"],
                complete_suite=(len(trials) == report["planned_trials"]
                                and len(selected) == len(cases)),
            )
        atomic_write(
            path, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        )

    save()
    for repeat in range(1, repeats + 1):
        for case_index, case in enumerate(selected):
            # 受控变体在各 case/repeat 间轮换顺序；减弱 Provider 排队与缓存的固定先后偏差。
            rotated = (
                (case_index + repeat - 1) % len(arms)
                if all(arm in CONTEXT_BENCHMARK_ARMS for arm in arms) else 0
            )
            case_arms = tuple(arms[rotated:]) + tuple(arms[:rotated])
            for order, arm in enumerate(case_arms):
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
                    trial = _trial(
                        trial_root, case, arm, settings, provider,
                        context_mechanisms=CONTEXT_BENCHMARK_ARMS.get(arm),
                    )
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
                trial["block_order"] = order
                if arm in CONTEXT_BENCHMARK_ARMS:
                    trial.setdefault("harness_mechanisms", list(CONTEXT_BENCHMARK_ARMS[arm]))
                report["trials"].append(trial)
                save()
                if on_trial:
                    on_trial(trial)
    report["complete_suite"] = len(report["trials"]) == report["planned_trials"]
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    return report
