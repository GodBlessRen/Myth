"""冻结 Oracle 的 Semantic Contract 离线消融：与相同 JSON selector 的裸抽取进行逐 Case 配对。

只测试确定性 JSON Mapping + Evidence/Constraint；不调用 Provider，不测量 token，
不声称真实 Agent 问答胜率，也不给信息解析策略提供自动 Promote 权限。
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from math import ceil
from pathlib import Path
import tempfile
from time import perf_counter_ns
from typing import Any

from .domain import canonical_json
from .platform.evaluation import (
    EvalCase, EvalObservation, EvalSuite, EvalVerdict, load_eval_suite,
    summarize_observations,
)
from .platform.semantic_contract import evaluate_json_mapping
from .runtime import MythRuntime
from .workspace import Workspace


# 支持的试验注入与预期状态固定列举；不要用任意代码/表达式驱动测试执行。
_MUTATIONS = {"none", "revise_source", "revoke_source", "revoke_ancestor"}
_STATUSES = {"resolved", "invalid", "stale", "conflict", "constraint_violation"}
_MODES = ("bare_selector", "semantic_contract")


# _percentile：仅描述当前离线样本的顺序统计量，小样本 p95 不代表生产尾延迟。
def _percentile(samples: list[float], level: float) -> float:
    if not samples:
        raise ValueError("latency sample set cannot be empty")
    values = sorted(samples)
    return round(values[max(0, ceil(len(values) * level) - 1)], 4)


# _arm_observation：复用既有 EvalObservation 格式，使 Oracle、分母和缺测语义保持一致。
def _arm_observation(
    case: EvalCase, arm: str, output: dict[str, Any],
    expected: dict[str, Any], samples: list[float], sample_bytes: list[int],
    suite_digest: str,
) -> EvalObservation:
    exact_status = output.get("status") == expected["status"]
    exact_value = (
        "value" not in expected or (
            output.get("status") == "resolved"
            and type(output.get("value")) is type(expected["value"])
            and output["value"] == expected["value"]
        )
    )
    valid = exact_status and exact_value
    verdict = EvalVerdict.PASS if valid else EvalVerdict.FAIL
    reason = (
        "fixed independent oracle matched"
        if valid else "fixed independent oracle rejected arm output"
    )
    refs = tuple(output.get("source_refs") or ())
    return EvalObservation(
        case_id=case.case_id, verdict=verdict, reason=reason,
        metrics={
            "wall_ms": _percentile(samples, 0.5),
            "tool_bytes": round(sum(sample_bytes) / len(sample_bytes), 2),
            "samples": len(samples),
        },
        evidence_refs=refs,
        safety_regression=case.safety_critical and not valid,
        policy_id="semantic-ablation:" + arm + ":v1",
        comparison_key=f"{suite_digest}:{case.case_id}",
        mechanism_events=(("semantic_contract",) if arm == "semantic_contract" else ()),
    )


# _bare_selector：同一确切字段路径/聚合、同一 SQLite 来源；刻意不做额外证据/单位/约束验证。
def _bare_selector(workspace, case: EvalCase, source_ids: list[str]) -> dict[str, Any]:
    """强基线：不依赖模型或模糊关键词，只比较新增校验产生的效果。"""
    try:
        values = []
        for source_id in source_ids:
            text = workspace.memory.get(source_id)["text"]
            document = json.loads(text)
            value = evaluate_json_mapping(
                document,
                {"unit": None},
                {
                    "pointer": case.input["pointer"],
                    "aggregation": case.input["aggregation"],
                    "unit_pointer": None,
                },
            )
            values.append(value)
        # 裸选择器没有可信多来源仲裁；取第一个可读值而不伪造共识。
        return {"status": "resolved", "value": values[0], "verified": False}
    except (ValueError, TypeError, KeyError, OverflowError):
        return {"status": "invalid", "value": None, "verified": False}


# SemanticAblationRunner：冻结数据、相同条件的 A/B 执行、统计/账本归一集中在一个深接口。
class SemanticAblationRunner:
    # 构建固定集后一次性校验形状与 Oracle；不在观测之后改题或筛掉失败例。
    def __init__(self, suite: EvalSuite, *, repeats: int = 3, seed: int = 17):
        # suite：固定版本、独立 Oracle 的既有 Evaluation 合同。
        self.suite = suite
        # repeats：重复测量序数；同 Case 重复不算作新的独立题。
        self.repeats = repeats
        # seed：确定 A/B 交错顺序；不是可用来挑选更佳实验的随机优化参数。
        self.seed = seed
        if suite.suite_id != "semantic-contract-offline-ablation" or suite.version != 1:
            raise ValueError("unsupported fixed semantic ablation suite")
        if type(repeats) is not int or not 1 <= repeats <= 12:
            raise ValueError("semantic ablation requires 1-12 repeated measurements")
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ValueError("semantic ablation requires a bounded deterministic seed")
        if len(suite.cases) < 8:
            raise ValueError("semantic ablation requires a nontrivial fixed denominator")
        for case in suite.cases:
            self._validate_case(case)
        self.suite_digest = hashlib.sha256(
            canonical_json({
                "suite_id": suite.suite_id, "version": suite.version,
                "cases": [asdict(case) for case in suite.cases],
            }).encode("utf-8")
        ).hexdigest()

    # from_path：复用已有 JSON EvalSuite 加载器，不新增另一种身份格式或迁移路径。
    @classmethod
    def from_path(
        cls, path: str | Path, *, repeats: int = 3, seed: int = 17
    ) -> "SemanticAblationRunner":
        return cls(load_eval_suite(path), repeats=repeats, seed=seed)

    # _validate_case：固定有限试验语法；所有测试输入/预期在执行前可人工检查。
    @staticmethod
    def _validate_case(case: EvalCase) -> None:
        raw = case.input
        expected = case.expected
        allowed = {
            "term_id", "documents", "pointer", "aggregation",
            "value_type", "unit", "unit_pointer", "constraints", "mutation",
        }
        if case.category != "semantic_contract" or set(raw) != allowed:
            raise ValueError("semantic eval case has unknown category/input keys")
        if (
            not isinstance(raw["documents"], list)
            or not 1 <= len(raw["documents"]) <= 4
            or raw["mutation"] not in _MUTATIONS
            or not isinstance(expected, dict)
            or set(expected) not in ({"status"}, {"status", "value"})
            or expected.get("status") not in _STATUSES
            or (expected["status"] == "resolved") != ("value" in expected)
        ):
            raise ValueError("semantic eval case has invalid inputs or frozen expected")
        if raw["mutation"] != "none" and len(raw["documents"]) != 1:
            raise ValueError("semantic mutation requires one fixed source")
        if len(raw["documents"]) > 4 or len(case.case_id) > 80:
            raise ValueError("semantic eval case exceeds fixed bounds")

    # _prepare：每一独立 Case 都在新 SQLite Runtime 中写入原始来源，再冻结合同和变更序列。
    @staticmethod
    def _prepare(workspace, case: EvalCase) -> tuple[list[str], float]:
        started = perf_counter_ns()
        raw = case.input
        ancestor = None
        if raw["mutation"] == "revoke_ancestor":
            ancestor = workspace.memory.remember(
                kind="episodic", text="fixture provenance root",
                source_ref=f"eval:{case.case_id}:ancestor",
            )
        ids = []
        for index, document in enumerate(raw["documents"]):
            body = (
                document if isinstance(document, str)
                else json.dumps(document, sort_keys=True, ensure_ascii=False)
            )
            record = workspace.memory.remember(
                kind="semantic", text=body,
                source_ref=f"eval:{case.case_id}:source:{index}",
                evidence=(
                    [{"source_memory_id": ancestor["memory_id"]}]
                    if ancestor is not None else None
                ),
            )
            ids.append(record["memory_id"])

        contract = {
            "term_id": raw["term_id"],
            "definition": "Fixed offline oracle mapping " + case.case_id,
            "value_type": raw["value_type"],
            "unit": raw["unit"],
            "mappings": [{
                "source_memory_id": source_id,
                "pointer": raw["pointer"],
                "aggregation": raw["aggregation"],
                "unit_pointer": raw["unit_pointer"],
            } for source_id in ids],
            "constraints": raw["constraints"],
        }
        proposed = workspace.semantics.propose(contract)
        if proposed.get("status") != "ready":
            raise ValueError("semantic fixture proposal could not be admitted")

        # 变更严格发生在提案之后，确保正式求值不会重新绑定已失效的证据。
        mutation = raw["mutation"]
        if mutation == "revise_source":
            workspace.memory.apply_delta(
                ids[0],
                [{"op": "replace_text", "text": json.dumps({"net": 999})}],
                expected_revision=1,
            )
        elif mutation == "revoke_source":
            workspace.memory.revoke(ids[0])
        elif mutation == "revoke_ancestor":
            workspace.memory.revoke(ancestor["memory_id"])

        setup_ms = (perf_counter_ns() - started) / 1_000_000
        return ids, setup_ms

    # _case_pair：两臂使用同一真实来源快照、同一 selector，AB/BA 次序冻结且不重置 Oracle。
    def _case_pair(self, case: EvalCase, ordinal: int) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="myth-semantic-eval-") as folder:
            with MythRuntime(Path(folder)) as runtime:
                workspace = Workspace(runtime)
                source_ids, setup_ms = self._prepare(workspace, case)
                samples = {mode: [] for mode in _MODES}
                byte_samples = {mode: [] for mode in _MODES}
                outputs: dict[str, dict[str, Any]] = {}
                for repeat in range(self.repeats):
                    order = (
                        _MODES if (self.seed + ordinal + repeat) % 2 == 0
                        else tuple(reversed(_MODES))
                    )
                    for arm in order:
                        started = perf_counter_ns()
                        outcome = (
                            _bare_selector(workspace, case, source_ids)
                            if arm == "bare_selector"
                            else workspace.semantics.evaluate(case.input["term_id"])
                        )
                        samples[arm].append((perf_counter_ns() - started) / 1_000_000)
                        byte_samples[arm].append(
                            len(canonical_json(outcome).encode("utf-8"))
                        )
                        # 同一冻结输入若返回不同结构或值，拒绝把最后一次结果当成确定性真值。
                        comparable = (outcome.get("status"), outcome.get("value"))
                        if arm in outputs and comparable != (
                            outputs[arm].get("status"), outputs[arm].get("value")
                        ):
                            raise ValueError("deterministic semantic evaluation changed between repeats")
                        outputs[arm] = outcome

                return {
                    "case_id": case.case_id,
                    "safety_critical": case.safety_critical,
                    "expected": dict(case.expected),
                    "setup_ms": round(setup_ms, 4),
                    "arms": {
                        arm: {
                            "output": outputs[arm],
                            "p50_ms": _percentile(samples[arm], 0.5),
                            "p95_ms": _percentile(samples[arm], 0.95),
                            "observation": _arm_observation(
                                case, arm, outputs[arm], case.expected,
                                samples[arm], byte_samples[arm], self.suite_digest,
                            ),
                        }
                        for arm in _MODES
                    },
                }

    # run：一次冻结完整分母的本地研究；过滤只标 partial，永不生成可发布的 Evolution 资格。
    def run(
        self, case_ids: tuple[str, ...] | None = None,
        *, ledger=None,
    ) -> dict[str, Any]:
        all_ids = {case.case_id for case in self.suite.cases}
        selected = set(case_ids or ())
        if selected - all_ids:
            raise ValueError("semantic evaluation contains unknown case ids")
        if case_ids is not None and len(selected) != len(case_ids):
            raise ValueError("semantic evaluation case selection contains duplicates")
        ordered = [
            case for case in self.suite.cases
            if case_ids is None or case.case_id in selected
        ]
        if not ordered:
            raise ValueError("semantic evaluation has no selected cases")
        results = [self._case_pair(case, i) for i, case in enumerate(ordered)]
        complete = len(ordered) == len(self.suite.cases)
        # 逐题观察与现有 Evaluation Ledger 同构；不重新解释 PASS/FAIL。
        observations = {
            arm: [result["arms"][arm]["observation"] for result in results]
            for arm in _MODES
        }
        payloads = {}
        for arm in _MODES:
            report = summarize_observations(self.suite.suite_id, observations[arm])
            payloads[arm] = {
                "suite_id": self.suite.suite_id,
                "version": self.suite.version,
                "policy_id": "semantic-ablation:" + arm + ":v1",
                "suite_case_count": len(self.suite.cases),
                "selected_case_count": len(ordered),
                "complete_suite": complete,
                "evaluation_partition": "discovery",
                "report": asdict(report),
                "observations": [
                    {**asdict(item), "verdict": item.verdict.value}
                    for item in observations[arm]
                ],
                # 离线实验是描述性证据，不得借用 information_resolution 的正式 Promote 门。
                "release_gate": {
                    "passed": False,
                    "reason": "offline descriptive selector ablation is not held-out provider qualification",
                },
            }

        before = observations["bare_selector"]
        after = observations["semantic_contract"]
        wins = sum(
            a.verdict is EvalVerdict.FAIL and b.verdict is EvalVerdict.PASS
            for a, b in zip(before, after)
        )
        losses = sum(
            a.verdict is EvalVerdict.PASS and b.verdict is EvalVerdict.FAIL
            for a, b in zip(before, after)
        )
        summary = {
            "suite_id": self.suite.suite_id,
            "version": self.suite.version,
            "suite_sha256": self.suite_digest,
            "repeats": self.repeats,
            "seed": self.seed,
            "case_count": len(self.suite.cases),
            "measured_case_count": len(results),
            "complete_suite": complete,
            "baseline_pass": sum(item.verdict is EvalVerdict.PASS for item in before),
            "candidate_pass": sum(item.verdict is EvalVerdict.PASS for item in after),
            "candidate_wins": wins,
            "candidate_losses": losses,
            "candidate_ties": len(results) - wins - losses,
            "baseline_unsafe_values": sum(
                entry["safety_critical"]
                and entry["expected"]["status"] != "resolved"
                and entry["arms"]["bare_selector"]["output"]["status"] == "resolved"
                for entry in results
            ),
            "candidate_unsafe_values": sum(
                entry["safety_critical"]
                and entry["expected"]["status"] != "resolved"
                and entry["arms"]["semantic_contract"]["output"]["status"] == "resolved"
                for entry in results
            ),
            "token_usage": None,
            "provider_cost": None,
            "model_quality_claim": False,
            "release_eligible": False,
            "measurement": "offline same-selector ablation; local wall-clock microbench only",
        }
        if ledger is not None:
            # 记录仅写入已有 Evaluation 所有者；两个变体均归 discovery，不能推广为政策发布权限。
            recorded = {
                arm: ledger.record(payloads[arm], policy_id=payloads[arm]["policy_id"])
                for arm in _MODES
            }
            summary["evaluation_run_ids"] = {
                arm: item["eval_run_id"] for arm, item in recorded.items()
            }
        return {
            "summary": summary,
            "variants": payloads,
            "cases": [{
                "case_id": result["case_id"],
                "safety_critical": result["safety_critical"],
                "expected": result["expected"],
                "setup_ms": result["setup_ms"],
                "bare_selector": {
                    "status": result["arms"]["bare_selector"]["output"]["status"],
                    "verdict": result["arms"]["bare_selector"]["observation"].verdict.value,
                    "p50_ms": result["arms"]["bare_selector"]["p50_ms"],
                    "p95_ms": result["arms"]["bare_selector"]["p95_ms"],
                },
                "semantic_contract": {
                    "status": result["arms"]["semantic_contract"]["output"]["status"],
                    "verdict": result["arms"]["semantic_contract"]["observation"].verdict.value,
                    "p50_ms": result["arms"]["semantic_contract"]["p50_ms"],
                    "p95_ms": result["arms"]["semantic_contract"]["p95_ms"],
                },
            } for result in results],
        }
