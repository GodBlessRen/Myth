"""Context Governance 的纯选择规则：相关性只排序，显式因果依赖保护未决执行事实。
本模块不读取仓储或调用模型；来源必须由调用方先按既有权限/作用域准入。
Tool Result 的状态是记录下来的报告，不因此升级为独立验收、权限或因果证明。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


# _CRITICAL：已记录的失败/未决状态标签；未知结果宁可保留导航，也不能当成功删去。
_CRITICAL = frozenset({
    "UNKNOWN", "FAILED", "ERROR", "INCONCLUSIVE", "BLOCKED",
    "SKIPPED", "REJECTED", "CANCELLED", "PENDING",
})
# _REFERENCE：只接受可导航的短身份；不把任意 Tool 正文复制进因果摘要。
_REFERENCE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,200}$")
# _WORD：英文词项与中文连续词段；这是保守词面估计，不是语义理解或因果置信度。
_WORD = re.compile(r"[a-z0-9_]{3,}|[\u4e00-\u9fff]+")


# 为模型和报表保留身份而非未知正文；非法/过长身份不可冒充可回读引用。
def _reference(value: object) -> str | None:
    return value if isinstance(value, str) and _REFERENCE.fullmatch(value) else None


# 将显式声明的依赖限定为当前记录的短 ID；声明只能作为导航线索，不能证明先决条件满足。
def _dependencies(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(dict.fromkeys(
        ref for item in value[:32] if (ref := _reference(item)) is not None
    ))


# 从持久活动提取确定性的关键状态标签；状态文本来自记录，绝不声称已独立验证。
def _critical_labels(activity: Mapping[str, Any]) -> tuple[str, ...]:
    labels: list[str] = []
    state = activity.get("state")
    if isinstance(state, str) and state.upper() in _CRITICAL:
        labels.append("step:" + state.upper())
    result = activity.get("result")
    if isinstance(result, Mapping):
        status = result.get("status")
        if isinstance(status, str) and status.upper() in _CRITICAL:
            labels.append("tool_report:" + status.upper())
        if result.get("error"):
            labels.append("tool_report:error_present")
        failure = result.get("failure")
        if isinstance(failure, Mapping):
            code = _reference(failure.get("code"))
            labels.append("known_failure:" + (code or "unspecified"))
        if result.get("adoption") == "rejected":
            labels.append("subagent_review:rejected")
        if result.get("adoption") == "pending_review":
            labels.append("subagent_review:pending")
        # 并行批次的子结果保留在父步骤收据中，不能因外层 status=OK 丢掉失败的子项。
        children = result.get("results")
        if isinstance(children, list):
            for index, child in enumerate(children[:3]):
                if not isinstance(child, Mapping):
                    continue
                status = child.get("status")
                if isinstance(status, str) and status.upper() in _CRITICAL:
                    labels.append("child_" + str(index) + ":" + status.upper())
                adoption = child.get("adoption")
                if adoption in {"rejected", "pending_review"}:
                    labels.append("child_" + str(index) + ":review_" + adoption)
        fused = result.get("fused_successor")
        if isinstance(fused, Mapping):
            successor_status = fused.get("status")
            if isinstance(successor_status, str) and successor_status.upper() in _CRITICAL:
                labels.append("successor_report:" + successor_status.upper())
    return tuple(dict.fromkeys(labels))


# 只提炼需保护的执行事实及其显式前驱；时间先后不自动推断成因果边。
def build_causal_guard(
    activities: Sequence[Mapping[str, Any]],
    runtime_liabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """返回有界字段的关键依赖导航；无关键状态时不占用额外 Context。"""
    nodes: list[dict[str, Any]] = []
    by_decision: dict[str, int] = {}
    critical: set[int] = set()
    for index, activity in enumerate(activities):
        result = activity.get("result")
        result = result if isinstance(result, Mapping) else {}
        step = activity.get("step")
        ref = f"activity:{step}" if type(step) is int and step >= 0 else f"activity-index:{index}"
        decision_id = _reference(activity.get("decision_id"))
        labels = _critical_labels(activity)
        declared = list(_dependencies(activity.get("declared_dependencies")))
        handoff = result.get("handoff")
        if isinstance(handoff, Mapping):
            declared.extend(_dependencies(handoff.get("depends_on")))
        children = result.get("results")
        aliases: list[str] = []
        if isinstance(children, list):
            for child in children[:3]:
                if isinstance(child, Mapping):
                    alias = _reference(child.get("delegation_id"))
                    if alias:
                        aliases.append(alias)
                    handoff = child.get("handoff")
                    if isinstance(handoff, Mapping):
                        declared.extend(_dependencies(handoff.get("depends_on")))
        else:
            alias = _reference(result.get("delegation_id"))
            if alias:
                aliases.append(alias)
        declared = list(dict.fromkeys(declared))
        row: dict[str, Any] = {
            "source": ref,
            "decision_id": decision_id,
            "capability": _reference(activity.get("capability")),
            "reported_outcomes": list(labels),
            "declared_dependencies": declared,
            "evidence_ref": _reference(result.get("evidence_ref")),
            "child_delegation_ids": aliases,
        }
        if labels:
            critical.add(index)
        for candidate in ([decision_id] if decision_id else []) + aliases:
            if candidate not in by_decision:
                by_decision[candidate] = index
        nodes.append(row)

    # Runtime 未结算操作与预算不一定已经成为步骤 Result；它们由同 Run 的权威账本投影。
    # 身份损坏时拒绝编译，不能因渲染格式错误而静默隐藏一条 UNKNOWN。
    if isinstance(runtime_liabilities, Mapping):
        for kind, key, ref_key, identity_field in (
            ("tool", "operations", "decision_id", "decision_id"),
            ("model", "models", "model_attempt_id", "model_attempt_id"),
        ):
            rows = runtime_liabilities.get(key) or []
            if not isinstance(rows, (list, tuple)):
                raise ValueError("invalid runtime liability collection")
            for row in rows:
                if not isinstance(row, Mapping) or row.get("state") not in {"TICKETED", "UNKNOWN"}:
                    raise ValueError("invalid unresolved Runtime state")
                identity = _reference(row.get(ref_key))
                if identity is None:
                    raise ValueError("unrepresentable unresolved Runtime identity")
                node = {
                    "source": "runtime-" + kind + ":" + identity,
                    "decision_id": identity if kind == "tool" else None,
                    "model_attempt_id": identity if kind == "model" else None,
                    "capability": _reference(row.get("capability")) if kind == "tool" else None,
                    "ticket_id": _reference(row.get("ticket_id")) if kind == "tool" else None,
                    "reported_outcomes": ["runtime_" + kind + ":" + str(row["state"])],
                    "declared_dependencies": [],
                    "evidence_ref": None,
                }
                index = len(nodes)
                nodes.append(node)
                critical.add(index)
                if kind == "tool" and identity not in by_decision:
                    by_decision[identity] = index
        cursor = runtime_liabilities.get("cursor")
        if isinstance(cursor, Mapping) and (
            cursor.get("recovery_state") == "RECONCILE"
            or cursor.get("phase") == "OUTCOME_UNKNOWN"
        ):
            nodes.append({
                "source": "runtime-cursor", "decision_id": None,
                "reported_outcomes": ["runtime_cursor:RECONCILE"],
                "declared_dependencies": [], "evidence_ref": None,
                "checkpoint_step": cursor.get("checkpoint_step")
                if type(cursor.get("checkpoint_step")) is int else None,
            })
            critical.add(len(nodes) - 1)
        holds = runtime_liabilities.get("unknown_held") or []
        if not isinstance(holds, (list, tuple)):
            raise ValueError("invalid Runtime budget holds")
        for hold in holds:
            if not isinstance(hold, Mapping):
                raise ValueError("invalid Runtime budget hold")
            meter = _reference(hold.get("meter"))
            units = hold.get("units")
            if meter is None or type(units) is not int or units <= 0:
                raise ValueError("invalid Runtime unknown-held meter")
            nodes.append({
                "source": "runtime-budget:" + meter, "decision_id": None,
                "reported_outcomes": ["runtime_budget:UNKNOWN_HELD"],
                "meter": meter, "units": units,
                "declared_dependencies": [], "evidence_ref": None,
            })
            critical.add(len(nodes) - 1)
    if not critical:
        return None

    # 只遍历已记录的显式依赖闭包；循环和重边由 visited 截止，不凭空制造丢失的前驱。
    protected = set(critical)
    missing: set[str] = set()
    frontier = list(sorted(critical))
    while frontier:
        index = frontier.pop()
        for dependency in nodes[index]["declared_dependencies"]:
            predecessor = by_decision.get(dependency)
            if predecessor is None:
                missing.add(dependency)
            elif predecessor not in protected:
                protected.add(predecessor)
                frontier.append(predecessor)

    records = [
        {**nodes[index], "role": "critical" if index in critical else "declared_predecessor"}
        for index in sorted(protected)
    ]
    return {
        "policy": "causal-context-guard-v1",
        "source": "persisted-activity-and-runtime-ledger-projection" if runtime_liabilities else "persisted-activity-projection",
        "semantics": "reported_outcomes_and_declared_dependencies_not_causal_proof",
        "critical_count": len(critical),
        "records": records,
        "missing_declared_dependencies": sorted(missing),
    }


# 生成稳定字节和摘要，外层用 required=True 装箱；Context 溢出时拒绝而非删关键记录。
def render_causal_guard(guard: Mapping[str, Any]) -> tuple[str, str]:
    """保留短导航而不拷贝大结果；所有原始事实继续由其仓储拥有。"""
    payload = json.dumps(
        guard, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    message = (
        "关键执行状态与声明的依赖（来自持久记录；不是独立验收或授权）：\n"
        + payload
        + "\nUNKNOWN 必须先通过 Runtime 核对；状态不明不能推定失败或安全重试。"
        "如需详情，使用原 decision_id 回读持久 Observation。"
    )
    return message, digest


# 只提取有限的字词作为粗排信号；无文本证据时返回 0，不能伪造语义相似度。
def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in _WORD.findall(text.lower()[:4096]):
        if "\u4e00" <= token[0] <= "\u9fff":
            terms.update(token[i : i + 2] for i in range(max(1, len(token) - 1)))
        else:
            terms.add(token)
    return terms


# 当前任务的词面相关性仅影响可选检索资料的相对排序，不影响事实等级、权限或 required。
def lexical_relevance(query: str, content: str) -> float:
    """返回 [0,1] 的可复现词面覆盖率；不宣称为 embedding 或实测信息增益。"""
    task_terms = _terms(query[:4096])
    if not task_terms:
        return 0.0
    source_terms = _terms(content[:4096])
    return round(len(task_terms & source_terms) / len(task_terms), 4)


# 提取本轮用户真实输入作为排序依据；避免让旧助手回复或历史检索重写用户目标。
def current_task_query(messages: Sequence[Mapping[str, Any]], start: int) -> str:
    """最多两段当前 Turn 的用户原文，单段有界；空任务则保持原检索顺序。"""
    recent = [
        str(message.get("content") or "")[:1024]
        for message in reversed(messages[start:])
        if message.get("role") == "user"
    ][:2]
    return " ".join(recent)[:2048]
