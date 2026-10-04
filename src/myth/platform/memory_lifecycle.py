"""Memory 生命周期的纯规则模块。
把证据输入、受约束 Delta 与 freshness 判定收敛为确定性规则；不访问 SQLite、不调用模型，也不授予执行权限。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping


# MemoryDeltaError：Delta 形状、证据或文本违反稳定合同；调用方应保持原 revision 不变。
class MemoryDeltaError(ValueError):
    """Memory Delta 无法安全应用。"""


# _text_value：统一校验 Memory 正文；字节上限与持久 Store 保持一致，避免不同入口产生不同合法集。
def _text_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text.encode("utf-8")) > 16_000:
        raise MemoryDeltaError("memory text must contain 1-16000 UTF-8 bytes")
    return text


# normalize_evidence_input：只接受稳定证据字段；source_revision 由权威 Store 读取，不能由模型/调用方自报。
def normalize_evidence_input(
    value: Mapping[str, Any],
    *,
    default_ref: str | None = None,
) -> dict[str, str | None]:
    if not isinstance(value, Mapping):
        raise MemoryDeltaError("memory evidence must be an object")
    allowed = {
        "evidence_ref",
        "source_memory_id",
        "quote",
        "relevance",
        "occurred_at",
    }
    unknown = set(value) - allowed
    if unknown:
        raise MemoryDeltaError(
            f"unknown memory evidence fields: {', '.join(sorted(unknown))}"
        )

    source_memory_id = str(value.get("source_memory_id") or "").strip() or None
    evidence_ref = str(value.get("evidence_ref") or "").strip() or None
    if evidence_ref is None and source_memory_id is None:
        evidence_ref = str(default_ref or "").strip() or None
    if evidence_ref is None and source_memory_id is None:
        raise MemoryDeltaError(
            "memory evidence requires evidence_ref or source_memory_id"
        )
    if evidence_ref is not None and len(evidence_ref) > 500:
        raise MemoryDeltaError("memory evidence_ref exceeds 500 characters")
    if source_memory_id is not None and len(source_memory_id) > 200:
        raise MemoryDeltaError("source_memory_id exceeds 200 characters")

    quote = str(value.get("quote") or "")
    if len(quote.encode("utf-8")) > 4_000:
        raise MemoryDeltaError("memory evidence quote exceeds 4000 UTF-8 bytes")
    relevance = str(value.get("relevance") or "").strip()
    if len(relevance) > 500:
        raise MemoryDeltaError("memory evidence relevance exceeds 500 characters")
    occurred_at = str(value.get("occurred_at") or "").strip() or None
    if occurred_at is not None and len(occurred_at) > 100:
        raise MemoryDeltaError("memory evidence occurred_at exceeds 100 characters")

    return {
        "evidence_ref": evidence_ref,
        "source_memory_id": source_memory_id,
        "quote": quote,
        "relevance": relevance,
        "occurred_at": occurred_at,
    }


# normalize_evidence_set：标准化一组当前证据并拒绝重复 ref；Evidence identity 对一个 Memory 必须无歧义。
def normalize_evidence_set(
    values: Iterable[Mapping[str, Any]] | None,
    *,
    default_ref: str | None = None,
) -> list[dict[str, str | None]]:
    source = list(values or ())
    if not source and default_ref:
        source = [{"evidence_ref": default_ref, "relevance": "provenance"}]
    normalized = [
        normalize_evidence_input(item, default_ref=default_ref) for item in source
    ]
    refs: set[str] = set()
    for item in normalized:
        ref = str(item.get("evidence_ref") or item.get("source_memory_id") or "")
        if ref in refs:
            raise MemoryDeltaError(f"duplicate memory evidence: {ref}")
        refs.add(ref)
    return normalized


# normalize_delta_operations：Delta 只描述“改正文 / 加证据 / 移证据”；未知字段整批拒绝，不猜模型意图。
def normalize_delta_operations(
    operations: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if isinstance(operations, (str, bytes, Mapping)):
        raise MemoryDeltaError("memory delta operations must be a list")
    normalized: list[dict[str, Any]] = []
    replace_count = 0
    for index, raw in enumerate(operations):
        if not isinstance(raw, Mapping):
            raise MemoryDeltaError(f"memory delta operation {index} must be an object")
        op = str(raw.get("op") or "").strip()
        if op == "replace_text":
            expected = {"op", "text"}
            if set(raw) != expected:
                raise MemoryDeltaError(
                    f"replace_text operation {index} must contain only op/text"
                )
            replace_count += 1
            if replace_count > 1:
                raise MemoryDeltaError(
                    "memory delta may contain at most one replace_text operation"
                )
            normalized.append({"op": op, "text": _text_value(raw["text"])})
            continue
        if op == "add_evidence":
            expected = {"op", "evidence"}
            if set(raw) != expected:
                raise MemoryDeltaError(
                    f"add_evidence operation {index} must contain only op/evidence"
                )
            normalized.append(
                {
                    "op": op,
                    "evidence": normalize_evidence_input(raw["evidence"]),
                }
            )
            continue
        if op == "remove_evidence":
            expected = {"op", "evidence_ref"}
            if set(raw) != expected:
                raise MemoryDeltaError(
                    f"remove_evidence operation {index} must contain only op/evidence_ref"
                )
            evidence_ref = str(raw.get("evidence_ref") or "").strip()
            if not evidence_ref or len(evidence_ref) > 500:
                raise MemoryDeltaError(
                    f"remove_evidence operation {index} requires a valid evidence_ref"
                )
            normalized.append({"op": op, "evidence_ref": evidence_ref})
            continue
        raise MemoryDeltaError(f"unsupported memory delta operation: {op or '<empty>'}")
    return tuple(normalized)


# apply_text_delta：纯函数只处理正文变化；Evidence 的来源 revision 必须由 Store 在事务内解析。
def apply_text_delta(current_text: str, operations: Iterable[Mapping[str, Any]]) -> str:
    text = _text_value(current_text)
    for operation in operations:
        if operation.get("op") == "replace_text":
            text = _text_value(operation.get("text"))
    return text


# evidence_json：revision snapshot 使用稳定 JSON；历史证据是审计事实而非可变当前表的别名。
def evidence_json(values: Iterable[Mapping[str, Any]]) -> str:
    payload = [dict(item) for item in values]
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


# evaluate_freshness：只对 source_memory_id 做可验证 freshness；外部 ref 没有版本水位时保持 untracked。
def evaluate_freshness(
    evidence: Iterable[Mapping[str, Any]],
    current_sources: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    rows = [dict(item) for item in evidence]
    linked = [item for item in rows if item.get("source_memory_id")]
    stale_sources: list[dict[str, Any]] = []
    for item in linked:
        source_id = str(item["source_memory_id"])
        source = current_sources.get(source_id)
        if source is None:
            stale_sources.append({"memory_id": source_id, "reason": "missing"})
            continue
        if not bool(source.get("active")):
            stale_sources.append({"memory_id": source_id, "reason": "revoked"})
            continue
        expected_revision = item.get("source_revision")
        current_revision = source.get("revision")
        if (
            expected_revision is None
            or int(expected_revision) != int(current_revision or 0)
        ):
            stale_sources.append(
                {
                    "memory_id": source_id,
                    "reason": "revision_changed",
                    "expected_revision": expected_revision,
                    "current_revision": current_revision,
                }
            )

    if stale_sources:
        status = "stale"
    elif linked:
        status = "fresh"
    else:
        status = "untracked"

    return {
        "status": status,
        "is_stale": bool(stale_sources),
        "linked_sources": len(linked),
        "external_evidence": len(rows) - len(linked),
        "stale_sources": stale_sources,
    }
