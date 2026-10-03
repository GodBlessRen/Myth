"""固定评测集、观测、配对比较与发布门槛合同。
仅 JSON 文件加载触及本地 I/O，质量比较和门槛计算为纯函数；未测量、部分集与不确定结果不会伪装完整通过。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
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
