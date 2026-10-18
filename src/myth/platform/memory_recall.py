"""多探针 Memory Recall 的纯合同。

将查询数量、稳定来源锚点和跨探针排序集中校验；本模块不读 SQLite、
不推断事实正确性，也不把检索排名升级为 Evidence/Verification。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from .retrieval import reciprocal_rank_scores


# 稳定引用必须包含 Memory 身份及冻结 revision；不可用模糊来源替代版本核对。
_MEMORY_REF = re.compile(r"^memory:(mem_[0-9a-f]{32})@([1-9][0-9]{0,9})$")


@dataclass(frozen=True)
class RecallPlan:
    """一次有界 SEEK：主查询、最多三条补充查询与必须核对的精确来源。"""

    # queries：已去重、长度受限的检索探针；同一请求最多四个。
    queries: tuple[str, ...]
    # required_refs：必须从权威仓储逐一核验的固定版本来源。
    required_refs: tuple[str, ...]
    # limit：本次输出候选上限；不可静默吞掉明确要求的引用。
    limit: int


def parse_memory_ref(value: str) -> tuple[str, int]:
    """只解析 Memory L0/L1/L2 发出的稳定引用，不支持猜测的文本别名。"""
    if not isinstance(value, str):
        raise ValueError("required memory reference must be a string")
    match = _MEMORY_REF.fullmatch(value)
    if match is None:
        raise ValueError("required memory reference must be memory:mem_<uuid>@<revision>")
    return match.group(1), int(match.group(2))


def build_recall_plan(
    query: str,
    *,
    probes: Iterable[str] | None = None,
    required_refs: Iterable[str] | None = None,
    limit: int = 6,
) -> RecallPlan:
    """在任何读库/向量调用前拒绝不受限请求；重复探针不产生第二次计费。"""
    # 步骤一：先检查总体预算及查询形状；拒绝生成器等不可预先限量的数据流。
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("memory recall limit must be 1-8")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
        raise ValueError("memory recall query must contain 1-500 characters")
    if probes is not None and not isinstance(probes, (list, tuple)):
        raise ValueError("memory recall probes must be a list")
    if required_refs is not None and not isinstance(required_refs, (list, tuple)):
        raise ValueError("memory recall required_refs must be a list")
    extra = tuple(probes or ())
    required = tuple(required_refs or ())
    if len(extra) > 3 or len(required) > 4:
        raise ValueError("memory recall exceeds the bounded probe/reference limit")
    if len(required) > limit:
        raise ValueError("memory recall limit cannot hide required references")

    # 步骤二：标准化并去重查询，保持调用方顺序但不重复消耗后端开销。
    queries = []
    seen_queries = set()
    for raw in (query, *extra):
        if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 500:
            raise ValueError("memory recall probes must contain 1-500 characters")
        text = raw.strip()
        key = text.casefold()
        if key not in seen_queries:
            queries.append(text)
            seen_queries.add(key)

    # 步骤三：精确引用先做形状与去重校验，版本有效性留给 SQLite 权威状态核验。
    seen_refs = set()
    refs = []
    for raw in required:
        parse_memory_ref(raw)
        if raw in seen_refs:
            raise ValueError("memory recall required references must be unique")
        refs.append(raw)
        seen_refs.add(raw)
    return RecallPlan(queries=tuple(queries), required_refs=tuple(refs), limit=limit)


def rank_probe_rows(
    rankings: Iterable[Iterable[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """RRF 仅融合每个探针的候选顺序；输出仍要回权威仓储核对身份和 revision。"""
    rows: dict[str, dict[str, Any]] = {}
    identities = []
    for ranking in rankings:
        refs = []
        for item in ranking:
            key = str(item.get("memory_id") or "")
            if not key:
                continue
            refs.append(key)
            rows.setdefault(key, dict(item))
        identities.append(tuple(refs))

    scores = reciprocal_rank_scores(tuple(identities))
    ranked = list(rows.values())
    ranked.sort(
        key=lambda row: (
            -scores.get(str(row["memory_id"]), 0.0),
            -int(row.get("revision") or 0),
            str(row["memory_id"]),
        )
    )
    return ranked
