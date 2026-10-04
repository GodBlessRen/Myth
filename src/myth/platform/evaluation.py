"""固定评测集、观测、配对比较与发布门槛合同。
仅 JSON 文件加载触及本地 I/O，质量比较和门槛计算为纯函数；未测量、部分集与不确定结果不会伪装完整通过。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from math import ceil
from pathlib import Path
from typing import Any, Iterable


# 固定评测的观测结论；缺证据/不支持不能算作 PASS。
class EvalVerdict(StrEnum):
    # PASS：固定验收/评测合同通过；资格只对当前证据身份有效。
    PASS = "PASS"
    # FAIL：固定验收/评测合同失败；不是供应商失联的替代状态。
    FAIL = "FAIL"
    # INCONCLUSIVE：证据不足以判定，保持显式不确定。
    INCONCLUSIVE = "INCONCLUSIVE"
    # UNSUPPORTED：该固定题未有测量实现；保持在完整分母，不能计为通过。
    UNSUPPORTED = "UNSUPPORTED"


# 固定输入与预期的单题合同；safety_critical 标明不允许优化牺牲的约束。
@dataclass(frozen=True)
class EvalCase:
    # case_id：固定评测题身份；不可随结果更改。
    case_id: str
    # category：固定探针类别；决定已登记测量方法。
    category: str
    # input：固定题目输入；评测时不改题刷分。
    input: dict[str, Any]
    # expected：独立固定预期；不能从模型结果生成期望。
    expected: dict[str, Any]
    # safety_critical：该题是否保护安全/恢复不变量；优化不能牺牲此项。
    safety_critical: bool = False

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self) -> None:
        if not self.case_id.strip() or not self.category.strip():
            raise ValueError("eval case id/category are required")


# 具有身份和版本的固定集合；重复题号拒绝，完整分母不会随结果改变。
@dataclass(frozen=True)
class EvalSuite:
    # suite_id：固定评测集身份；比较还须 version 一致。
    suite_id: str
    # version：固定合同/配置版本；历史比较必须保留版本身份。
    version: int
    # principle：集合明确测量范围；不声称超出样本的能力。
    principle: str
    # cases：固定完整题集合；筛选结果保留 partial 身份。
    cases: tuple[EvalCase, ...]

    # 在合同构造时校验输入边界；非法值提前拒绝，避免进入后续执行或比较。
    def __post_init__(self) -> None:
        if not self.suite_id.strip() or self.version < 1:
            raise ValueError("eval suite id/version are required")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("eval suite contains duplicate case ids")


# 某策略对某固定题的测量事实；未测量成本和不确定结论保持可见。
@dataclass(frozen=True)
class EvalObservation:
    # case_id：固定评测题身份；不可随结果更改。
    case_id: str
    # verdict：验收/评测结论；不足证据保留 INCONCLUSIVE。
    verdict: EvalVerdict
    # reason：可解释的选择/拒绝原因；不是授权证据。
    reason: str
    # metrics：已测量的各维成本/质量数据；缺项不等于零。
    metrics: dict[str, float | int] | None = None
    # evidence_refs：固定来源/收据引用集合；文本引用本身不能补造效果。
    evidence_refs: tuple[str, ...] = ()
    # safety_regression：是否观察到安全/Runtime 不变量回归。
    safety_regression: bool = False
    # policy_id：受测策略的固定身份，供配对和发布核对。
    policy_id: str | None = None
    # comparison_key：包含同题/同版本身份的配对键，防止跨条件刷分。
    comparison_key: str | None = None
    # mechanism_events：本题实际触发/应用/回退的优化机制身份；只做归因线索，不自动证明因果。
    mechanism_events: tuple[str, ...] = ()
    # harness_id：本次受控评测的完整 Harness 变体身份；普通评测可为空，放末尾保持旧位置参数兼容。
    harness_id: str | None = None


# 同题同版本身份下的策略配对结果；未测量质量保留 None，成本差异保持向量。
@dataclass(frozen=True)
class PairedEvalComparison:
    # case_id：固定评测题身份；不可随结果更改。
    case_id: str
    # comparison_key：包含同题/同版本身份的配对键，防止跨条件刷分。
    comparison_key: str
    # baseline_policy_id：配对基准策略身份；必须与活动/证据版本一致。
    baseline_policy_id: str
    # candidate_policy_id：配对候选策略身份；研究候选不直接改生产。
    candidate_policy_id: str
    # baseline_verdict：基准固定题观测结论。
    baseline_verdict: EvalVerdict
    # candidate_verdict：候选固定题观测结论。
    candidate_verdict: EvalVerdict
    # observed_quality_gain：同题已测质量差，缺证据为 None。
    observed_quality_gain: float | None
    # cost_delta：同题共同测量成本维度的差值向量。
    cost_delta: dict[str, float]
    # evidence_refs：固定来源/收据引用集合；文本引用本身不能补造效果。
    evidence_refs: tuple[str, ...] = ()

    # 只有 paired observed_quality_gain 已测量才为真；不把不确定 verdict 补成零。
    @property
    def calibrated(self) -> bool:
        return self.observed_quality_gain is not None


# 把 PASS/FAIL 映射为明确二值质量；INCONCLUSIVE/UNSUPPORTED 保留 None。
def _verdict_quality(verdict: EvalVerdict) -> float | None:
    if verdict is EvalVerdict.PASS:
        return 1.0
    if verdict is EvalVerdict.FAIL:
        return 0.0
    return None


# 要求同 case/comparison_key 与显式 policy 身份，再计算质量差及共同测量成本维度。
def compare_observations(
    baseline: EvalObservation,
    candidate: EvalObservation,
) -> PairedEvalComparison:
    if baseline.case_id != candidate.case_id:
        raise ValueError("paired evaluation requires the same case_id")
    baseline_key = baseline.comparison_key or baseline.case_id
    candidate_key = candidate.comparison_key or candidate.case_id
    if baseline_key != candidate_key:
        raise ValueError("paired evaluation requires the same comparison_key")
    if not baseline.policy_id or not candidate.policy_id:
        raise ValueError("paired evaluation requires explicit policy_id values")

    baseline_quality = _verdict_quality(baseline.verdict)
    candidate_quality = _verdict_quality(candidate.verdict)
    quality_gain = (
        None
        if baseline_quality is None or candidate_quality is None
        else candidate_quality - baseline_quality
    )
    baseline_metrics = baseline.metrics or {}
    candidate_metrics = candidate.metrics or {}
    keys = set(baseline_metrics) | set(candidate_metrics)
    cost_delta = {}
    for key in sorted(keys):
        before = baseline_metrics.get(key)
        after = candidate_metrics.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            cost_delta[key] = float(after) - float(before)

    return PairedEvalComparison(
        case_id=baseline.case_id,
        comparison_key=baseline_key,
        baseline_policy_id=baseline.policy_id,
        candidate_policy_id=candidate.policy_id,
        baseline_verdict=baseline.verdict,
        candidate_verdict=candidate.verdict,
        observed_quality_gain=quality_gain,
        cost_delta=cost_delta,
        evidence_refs=tuple(
            dict.fromkeys((*baseline.evidence_refs, *candidate.evidence_refs))
        ),
    )


# 固定评测的汇总；unsupported/inconclusive 仍在分母和发布门槛中。
@dataclass(frozen=True)
class EvalReport:
    # suite_id：固定评测集身份；比较还须 version 一致。
    suite_id: str
    # pass_count：固定集合通过题数；并非真实所有任务成功率。
    pass_count: int
    # fail_count：固定集合失败题数；不能筛出分母。
    fail_count: int
    # inconclusive_count：证据不充分题数；发布前保持可见。
    inconclusive_count: int
    # safety_regressions：安全/恢复不变量回归数量。
    safety_regressions: int
    # measured_cost：当前已报告标量 cost 汇总；不能代替完整真实用量测量。
    measured_cost: int | None = None
    # unsupported_count：运行器未支持题数；不是通过，也不静默省略。
    unsupported_count: int = 0

    # 计算包含 PASS/FAIL/INCONCLUSIVE/UNSUPPORTED 的完整题数。
    @property
    def total(self) -> int:
        return (
            self.pass_count
            + self.fail_count
            + self.inconclusive_count
            + self.unsupported_count
        )

    # 计算已执行观测的题数；unsupported 保持独立且会阻止发布。
    @property
    def measured_total(self) -> int:
        return self.pass_count + self.fail_count + self.inconclusive_count


# 严格加载本地固定 JSON 集并构造合同；题号和版本由合同校验。
def load_eval_suite(path: str | Path) -> EvalSuite:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("cases"), list):
        raise ValueError("eval suite must contain a cases array")
    cases = []
    for raw in value["cases"]:
        if not isinstance(raw, dict):
            raise ValueError("eval case must be an object")
        cases.append(
            EvalCase(
                case_id=str(raw.get("case_id") or ""),
                category=str(raw.get("category") or ""),
                input=dict(raw.get("input") or {}),
                expected=dict(raw.get("expected") or {}),
                safety_critical=bool(raw.get("safety_critical", False)),
            )
        )
    return EvalSuite(
        suite_id=str(value.get("suite_id") or ""),
        version=int(value.get("version") or 0),
        principle=str(value.get("principle") or ""),
        cases=tuple(cases),
    )


# 从完整集提取题目元组；调用方仍需保留 suite 身份才能发布比较。
def load_eval_cases(path: str | Path) -> tuple[EvalCase, ...]:
    return load_eval_suite(path).cases


# 汇总逐题结论及当前已报告 cost；缺测字段不能据此宣称零真实成本。
def summarize_observations(
    suite_id: str,
    observations: Iterable[EvalObservation],
) -> EvalReport:
    values = tuple(observations)
    return EvalReport(
        suite_id=suite_id,
        pass_count=sum(item.verdict is EvalVerdict.PASS for item in values),
        fail_count=sum(item.verdict is EvalVerdict.FAIL for item in values),
        inconclusive_count=sum(
            item.verdict is EvalVerdict.INCONCLUSIVE for item in values
        ),
        unsupported_count=sum(
            item.verdict is EvalVerdict.UNSUPPORTED for item in values
        ),
        safety_regressions=sum(bool(item.safety_regression) for item in values),
        measured_cost=sum(
            int((item.metrics or {}).get("cost", 0))
            for item in values
            if (item.metrics or {}).get("cost") is not None
        ),
    )


# 按完整题数、安全回归、不支持、不确定与通过率给资格；资格不自动 Promote。
def release_gate(
    report: EvalReport, *, min_pass_rate: float = 0.95
) -> tuple[bool, str]:
    if report.total <= 0:
        return False, "empty evaluation suite"
    if report.safety_regressions:
        return False, "safety/runtime invariant regression"
    if report.unsupported_count:
        return False, "unsupported cases remain"
    if report.measured_total <= 0:
        return False, "no measured evaluation cases"
    rate = report.pass_count / report.measured_total
    if rate < min_pass_rate:
        return False, f"pass rate {rate:.3f} below {min_pass_rate:.3f}"
    if report.inconclusive_count:
        return False, "inconclusive cases remain"
    return True, "quality gate passed"


# 只有这些明确成本 meter 参与默认效率门；检索命中数、附件数等业务指标不能被误当作“越少越好”的成本。
EFFICIENCY_METERS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "model_calls",
        "tool_calls",
        "steps",
        "write_bytes",
        "tool_bytes",
        "wall_ms",
        "provider_wall_ms",
        "changed_lines",
        "human_attention",
        "cost",
    }
)




# 从持久 JSON 报告恢复 EvalReport；缺失字段按旧版本兼容默认值处理，不重新计算观测。
def eval_report_from_dict(value: dict[str, Any]) -> EvalReport:
    return EvalReport(
        suite_id=str(value.get("suite_id") or ""),
        pass_count=int(value.get("pass_count") or 0),
        fail_count=int(value.get("fail_count") or 0),
        inconclusive_count=int(value.get("inconclusive_count") or 0),
        safety_regressions=int(value.get("safety_regressions") or 0),
        measured_cost=(
            None
            if value.get("measured_cost") is None
            else int(value.get("measured_cost"))
        ),
        unsupported_count=int(value.get("unsupported_count") or 0),
    )

# 能力下限 + Pareto 效率发布门：候选可以更省，但不能用未测/安全回归/超容差能力损失换取效率。
def capability_efficiency_gate(
    baseline: EvalReport,
    candidate: EvalReport,
    comparisons: Iterable[PairedEvalComparison],
    *,
    max_pass_rate_loss: float = 0.0,
    cost_meters: frozenset[str] = EFFICIENCY_METERS,
    require_improvement: bool = False,
) -> tuple[bool, str, dict[str, float]]:
    if baseline.suite_id != candidate.suite_id or baseline.total != candidate.total:
        return False, "baseline/candidate suite identity differs", {}
    if candidate.safety_regressions:
        return False, "safety/runtime invariant regression", {}
    if candidate.unsupported_count or candidate.inconclusive_count:
        return False, "candidate has unsupported or inconclusive cases", {}
    if baseline.measured_total <= 0 or candidate.measured_total <= 0:
        return False, "no measured paired capability", {}
    baseline_rate = baseline.pass_count / baseline.measured_total
    candidate_rate = candidate.pass_count / candidate.measured_total
    if candidate_rate + max_pass_rate_loss < baseline_rate:
        return (
            False,
            f"capability floor violated: {candidate_rate:.3f} < {baseline_rate:.3f} - {max_pass_rate_loss:.3f}",
            {},
        )
    aggregate: dict[str, float] = {}
    values = tuple(comparisons)
    if not values or any(not item.calibrated for item in values):
        return False, "paired attribution is incomplete", {}
    for item in values:
        for meter, delta in item.cost_delta.items():
            if meter not in cost_meters:
                continue
            aggregate[meter] = aggregate.get(meter, 0.0) + float(delta)
    if not aggregate:
        return False, "no common measured efficiency meters", {}
    if any(delta > 0 for delta in aggregate.values()):
        return False, "candidate is not Pareto-nonworse on measured efficiency", aggregate
    if require_improvement and not any(delta < 0 for delta in aggregate.values()):
        return False, "candidate has no measured efficiency improvement", aggregate
    return (
        True,
        (
            "capability floor held and measured efficiency improved"
            if any(delta < 0 for delta in aggregate.values())
            else "capability floor held and measured efficiency did not regress"
        ),
        aggregate,
    )


# 从同题不同 policy 的观测构造 task×policy 与 outcome flip 投影；只做归因导航，不把相关性冒充机制因果。
def attribution_matrix(
    observations: Iterable[EvalObservation],
    *,
    baseline_policy_id: str,
) -> dict[str, object]:
    values = tuple(observations)
    policies = sorted({item.policy_id for item in values if item.policy_id})
    if baseline_policy_id not in policies:
        raise ValueError("attribution requires an explicit observed baseline_policy_id")
    cases = sorted({item.case_id for item in values})
    matrix = {
        case_id: {
            policy: next(
                (
                    item.verdict.value
                    for item in values
                    if item.case_id == case_id and item.policy_id == policy
                ),
                None,
            )
            for policy in policies
        }
        for case_id in cases
    }
    flips = []
    if len(policies) >= 2:
        baseline = baseline_policy_id
        for candidate in (policy for policy in policies if policy != baseline):
            for case_id in cases:
                before = matrix[case_id][baseline]
                after = matrix[case_id][candidate]
                if before is not None and after is not None and before != after:
                    flips.append(
                        {
                            "case_id": case_id,
                            "baseline_policy_id": baseline,
                            "candidate_policy_id": candidate,
                            "baseline_verdict": before,
                            "candidate_verdict": after,
                            "candidate_mechanisms": sorted(
                                {
                                    mechanism
                                    for item in values
                                    if item.case_id == case_id
                                    and item.policy_id == candidate
                                    for mechanism in item.mechanism_events
                                }
                            ),
                        }
                    )
    return {
        "policies": policies,
        "baseline_policy_id": baseline_policy_id,
        "cases": cases,
        "matrix": matrix,
        "outcome_flips": flips,
        "causal_attribution": False,
        "note": "mechanism causality requires one-mechanism/leave-one-out or equivalent controlled reruns",
    }




# HarnessVariant 只描述一次受控评测使用的完整 Runtime/Harness 机制集合；它是 Evaluation 数据，不新增 Runtime 层。
@dataclass(frozen=True)
class HarnessVariant:
    # harness_id：受控实验中的稳定变体身份；同一身份必须代表同一机制集合。
    harness_id: str
    # mechanisms：本变体明确启用的机制身份；排序后参与比较，不从结果反推。
    mechanisms: tuple[str, ...] = ()

    # 构造时固定身份和机制集合；重复机制会让 one-mechanism/leave-one-out 语义含糊，因此拒绝。
    def __post_init__(self) -> None:
        if not self.harness_id.strip():
            raise ValueError("harness_id is required")
        values = tuple(item.strip() for item in self.mechanisms if item.strip())
        if len(values) != len(self.mechanisms) or len(values) != len(set(values)):
            raise ValueError("harness mechanisms must be unique non-empty strings")


# 为 full / one-mechanism / leave-one-out 生成去重后的 Harness 变体；只生成实验身份，不执行任务。
def controlled_harness_variants(
    mechanisms: Iterable[str], *, prefix: str = "harness"
) -> tuple[HarnessVariant, ...]:
    values = tuple(sorted({str(item).strip() for item in mechanisms if str(item).strip()}))
    if not values:
        raise ValueError("controlled harness experiment requires mechanisms")
    enabled_sets = {frozenset(), frozenset(values)}
    full = frozenset(values)
    for mechanism in values:
        enabled_sets.add(frozenset({mechanism}))
        enabled_sets.add(full - {mechanism})
    ordered = sorted(enabled_sets, key=lambda item: (len(item), tuple(sorted(item))))
    result = []
    for enabled in ordered:
        suffix = "none" if not enabled else "+".join(sorted(enabled))
        result.append(HarnessVariant(f"{prefix}:{suffix}", tuple(sorted(enabled))))
    return tuple(result)

# 只比较双方共同测量的数值 metric；缺测不能补零进入机制成本归因。
def _observed_metric_delta(
    before: EvalObservation, after: EvalObservation
) -> dict[str, float]:
    left = before.metrics or {}
    right = after.metrics or {}
    result = {}
    for key in sorted(set(left) & set(right)):
        if isinstance(left[key], (int, float)) and isinstance(right[key], (int, float)):
            result[key] = float(right[key]) - float(left[key])
    return result


# 受控归因只接受同题不同 Harness 变体的真实观测；没有对应消融 Run 时保持 insufficient，不靠总分猜原因。
def controlled_attribution(
    observations: Iterable[EvalObservation],
    variants: Iterable[HarnessVariant],
    *,
    baseline_harness_id: str,
    full_harness_id: str,
) -> dict[str, object]:
    values = tuple(observations)
    variant_values = tuple(variants)
    variant_map = {item.harness_id: item for item in variant_values}
    if len(variant_map) != len(variant_values):
        raise ValueError("controlled attribution requires unique harness ids")
    if baseline_harness_id not in variant_map or full_harness_id not in variant_map:
        raise ValueError("baseline/full harness variants are required")
    baseline_variant = variant_map[baseline_harness_id]
    full_variant = variant_map[full_harness_id]
    if baseline_variant.mechanisms:
        raise ValueError("baseline harness must contain no candidate mechanisms")
    full_mechanisms = frozenset(full_variant.mechanisms)
    if not full_mechanisms:
        raise ValueError("full harness must contain at least one mechanism")

    by_harness_case: dict[tuple[str, str], EvalObservation] = {}
    for item in values:
        harness_id = getattr(item, "harness_id", None)
        if not harness_id:
            continue
        key = (str(harness_id), item.case_id)
        if key in by_harness_case:
            raise ValueError("duplicate controlled observation for harness/case")
        by_harness_case[key] = item

    one_by_mechanism = {}
    leave_out_by_mechanism = {}
    for variant in variant_map.values():
        enabled = frozenset(variant.mechanisms)
        if len(enabled) == 1:
            one_by_mechanism[next(iter(enabled))] = variant.harness_id
        missing = full_mechanisms - enabled
        if len(missing) == 1 and enabled == full_mechanisms - missing:
            leave_out_by_mechanism[next(iter(missing))] = variant.harness_id

    cases = sorted(
        {
            item.case_id
            for item in values
            if getattr(item, "harness_id", None)
            in {baseline_harness_id, full_harness_id}
        }
    )
    effects = []
    for mechanism in sorted(full_mechanisms):
        one_id = one_by_mechanism.get(mechanism)
        leave_id = leave_out_by_mechanism.get(mechanism)
        for case_id in cases:
            baseline = by_harness_case.get((baseline_harness_id, case_id))
            full = by_harness_case.get((full_harness_id, case_id))
            one = by_harness_case.get((one_id, case_id)) if one_id else None
            leave = by_harness_case.get((leave_id, case_id)) if leave_id else None
            if baseline is None or full is None:
                continue
            classification = "insufficient"
            if one is not None and leave is not None:
                b = _verdict_quality(baseline.verdict)
                f = _verdict_quality(full.verdict)
                o = _verdict_quality(one.verdict)
                l = _verdict_quality(leave.verdict)
                if None not in {b, f, o, l}:
                    # Full 优于去掉 M 且 M 单独不差于 baseline，支持 M 对该题有正贡献。
                    if f > l and o >= b:
                        classification = "supported_benefit"
                    # Full 差于去掉 M 且 M 单独不优于 baseline，支持 M 对该题有负贡献。
                    elif f < l and o <= b:
                        classification = "supported_harm"
                    else:
                        classification = "mixed_or_interaction"
            full_vs_leave = (
                _observed_metric_delta(leave, full) if leave is not None else {}
            )
            one_vs_baseline = (
                _observed_metric_delta(baseline, one) if one is not None else {}
            )
            input_saving = (
                -full_vs_leave["input_tokens"]
                if full_vs_leave.get("input_tokens") is not None
                and full_vs_leave["input_tokens"] < 0
                else None
            )
            cache_write_delta = full_vs_leave.get("cache_write_input_tokens")
            cache_debt = (
                max(0.0, cache_write_delta)
                if cache_write_delta is not None
                else None
            )
            breakeven = (
                ceil(cache_debt / input_saving)
                if cache_debt is not None and input_saving is not None and input_saving > 0
                else None
            )
            effects.append(
                {
                    "case_id": case_id,
                    "mechanism": mechanism,
                    "baseline_harness_id": baseline_harness_id,
                    "full_harness_id": full_harness_id,
                    "one_mechanism_harness_id": one_id,
                    "leave_one_out_harness_id": leave_id,
                    "baseline_verdict": baseline.verdict.value,
                    "full_verdict": full.verdict.value,
                    "one_mechanism_verdict": one.verdict.value if one else None,
                    "leave_one_out_verdict": leave.verdict.value if leave else None,
                    "classification": classification,
                    "controlled": one is not None and leave is not None,
                    "full_vs_leave_cost_delta": full_vs_leave,
                    "one_vs_baseline_cost_delta": one_vs_baseline,
                    "input_token_saving_per_request": input_saving,
                    "cache_write_debt_tokens": cache_debt,
                    "breakeven_requests": breakeven,
                }
            )

    return {
        "baseline_harness_id": baseline_harness_id,
        "full_harness_id": full_harness_id,
        "mechanisms": sorted(full_mechanisms),
        "effects": effects,
        "controlled_effects": sum(item["controlled"] for item in effects),
        "supported_benefits": sum(
            item["classification"] == "supported_benefit" for item in effects
        ),
        "supported_harms": sum(
            item["classification"] == "supported_harm" for item in effects
        ),
        "note": (
            "supported_* requires both one-mechanism and leave-one-out observations; "
            "missing controlled reruns remain insufficient"
        ),
    }

# Search/Evolution 与最终发布评测必须物理上保持 case identity 不相交；final 结果不能反馈回候选搜索。
@dataclass(frozen=True)
class HeldOutEvalBoundary:
    # discovery_case_ids：允许反馈候选搜索/调参的固定 Case 身份。
    discovery_case_ids: tuple[str, ...]
    # final_case_ids：只用于最终接受/拒绝、禁止回流搜索的 Case 身份。
    final_case_ids: tuple[str, ...]

    # 构造时强制 discovery/final 身份互斥；重叠意味着 final 已不再 held-out。
    def __post_init__(self) -> None:
        discovery = set(self.discovery_case_ids)
        final = set(self.final_case_ids)
        if len(discovery) != len(self.discovery_case_ids) or len(final) != len(self.final_case_ids):
            raise ValueError("eval partition contains duplicate case ids")
        overlap = discovery & final
        if overlap:
            raise ValueError(
                "held-out final cases overlap discovery cases: " + ",".join(sorted(overlap))
            )

    # 只有 discovery 身份允许影响候选生成；final 只产生最终接受/拒绝证据。
    def may_feed_back(self, case_id: str) -> bool:
        return case_id in set(self.discovery_case_ids)
