"""显式替代证明的纯求值模块：OR-of-AND 只在受信任的 Proof Paths 声明下生效。
旧 Memory 默认 All-of；不执行外部效果，不提升 fact_level，也不授予 Verification。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .memory_lifecycle import MemoryDeltaError


# normalize_proof_paths：确保每条路径都是有来源版本的完整 AND；路径间采用 OR。
def normalize_proof_paths(
    paths: object, evidence: Iterable[Mapping[str, Any]]
) -> tuple[tuple[str, ...], ...]:
    """仅允许 2-8 条不同路径，引用已固定到 Memory revision 的当前证据。"""
    rows = list(evidence)
    linked = {
        str(row["evidence_ref"])
        for row in rows if row.get("source_memory_id")
    }
    if not isinstance(paths, (tuple, list)) or not 2 <= len(paths) <= 8:
        raise MemoryDeltaError("proof paths require 2-8 alternative AND groups")
    normalized = []
    seen = set()
    for index, group in enumerate(paths):
        if not isinstance(group, (tuple, list)) or not 1 <= len(group) <= 8:
            raise MemoryDeltaError(f"proof path {index} requires 1-8 evidence refs")
        if any(not isinstance(ref, str) or not ref or ref.strip() != ref for ref in group):
            raise MemoryDeltaError(f"proof path {index} has invalid evidence refs")
        if len(set(group)) != len(group):
            raise MemoryDeltaError(f"proof path {index} repeats evidence")
        if set(group) - linked:
            raise MemoryDeltaError(f"proof path {index} references unpinned evidence")
        canonical = tuple(sorted(group))
        if canonical in seen:
            raise MemoryDeltaError("duplicate proof path")
        normalized.append(canonical)
        seen.add(canonical)
    if set().union(*(set(group) for group in normalized)) != linked:
        raise MemoryDeltaError("proof paths must account for every linked evidence")
    return tuple(sorted(normalized))


# evaluate_alternative_closure：有界求值所有显式路径；普通节点退化为唯一 All-of。
def evaluate_alternative_closure(
    root_id: str,
    root_row: Mapping[str, Any],
    root_evidence: Iterable[Mapping[str, Any]],
    *,
    load: Callable[[str], tuple[Mapping[str, Any] | None, Iterable[Mapping[str, Any]]]],
    max_edges: int = 256,
    max_depth: int = 32,
) -> dict[str, Any]:
    """只有至少一条完整、有效的证明路径才保留结论；任何越权/成环依然一票否决。"""
    if type(max_edges) is not int or max_edges < 1 or type(max_depth) is not int or max_depth < 1:
        raise ValueError("support closure limits must be positive integers")

    cache: dict[str, tuple[dict[str, Any] | None, tuple[dict[str, Any], ...]]] = {}
    fatalities: list[dict[str, Any]] = []
    failed_paths: list[dict[str, Any]] = []
    checked_edges = 0
    selected_root_paths: list[int] = []

    # 仅缓存一次 SQLite 加载，不缓存与祖先路径相关的证明真假，以免隐藏跨路径循环。
    def source_state(source_id: str) -> tuple[dict[str, Any] | None, tuple[dict[str, Any], ...]]:
        if source_id not in cache:
            row, evidence = load(source_id)
            cache[source_id] = (
                dict(row) if row is not None else None,
                tuple(dict(item) for item in evidence),
            )
        return cache[source_id]

    # 判定一个 Memory 的所有证明路径：AND 内全部前提都有效，OR 至少有一组成功。
    def check(
        memory_id: str, row: Mapping[str, Any],
        evidence: tuple[dict[str, Any], ...], ancestors: tuple[str, ...], depth: int,
    ) -> tuple[bool, list[dict[str, Any]]]:
        nonlocal checked_edges
        invalid = row.get("_proof_paths_error")
        if invalid:
            issue = {"memory_id": memory_id, "reason": str(invalid), "path": list(ancestors)}
            fatalities.append(issue)
            return False, [issue]

        linked = {
            str(item["evidence_ref"]): item for item in evidence
            if item.get("source_memory_id")
        }
        declared = row.get("_proof_paths")
        if declared is None:
            groups = [tuple(sorted(linked))]
        else:
            # 即使 SQLite 原始定义被手工篡改，也不能用不完整的 AND 降低支持条件。
            try:
                groups = normalize_proof_paths(declared, evidence)
            except MemoryDeltaError:
                issue = {"memory_id": memory_id, "reason": "proof_paths_invalid",
                         "path": list(ancestors)}
                fatalities.append(issue)
                return False, [issue]

        winners = []
        all_failures = []
        for index, group in enumerate(groups):
            valid = True
            group_failures = []
            for reference in group:
                edge = linked[reference]
                source_id = str(edge["source_memory_id"])
                path = (*ancestors, source_id)
                if checked_edges >= max_edges:
                    issue = {"memory_id": source_id, "reason": "closure_limit", "path": list(path)}
                    fatalities.append(issue)
                    group_failures.append(issue)
                    valid = False
                    break
                checked_edges += 1
                if source_id in ancestors:
                    issue = {"memory_id": source_id, "reason": "dependency_cycle", "path": list(path)}
                    fatalities.append(issue)
                    group_failures.append(issue)
                    valid = False
                    continue
                if depth >= max_depth:
                    issue = {"memory_id": source_id, "reason": "depth_limit", "path": list(path)}
                    fatalities.append(issue)
                    group_failures.append(issue)
                    valid = False
                    continue
                source, dependencies = source_state(source_id)
                if source is None:
                    issue = {"memory_id": source_id, "reason": "missing", "path": list(path)}
                    fatalities.append(issue)
                    group_failures.append(issue)
                    valid = False
                    continue
                if source.get("scope_type") != "global" and (
                    source.get("scope_type") != row.get("scope_type")
                    or source.get("scope_id") != row.get("scope_id")
                ):
                    issue = {"memory_id": source_id, "reason": "scope_violation",
                             "path": list(path)}
                    fatalities.append(issue)
                    group_failures.append(issue)
                    valid = False
                    continue
                if not bool(source.get("active")):
                    group_failures.append({
                        "memory_id": source_id, "reason": "revoked", "path": list(path)
                    })
                    valid = False
                    continue
                expected = edge.get("source_revision")
                actual = source.get("revision")
                if type(expected) is not int or type(actual) is not int or expected != actual:
                    group_failures.append({
                        "memory_id": source_id, "reason": "revision_changed",
                        "expected_revision": expected, "current_revision": actual,
                        "path": list(path),
                    })
                    valid = False
                    continue
                child_valid, child_failures = check(
                    source_id, source, dependencies, path, depth + 1
                )
                if not child_valid:
                    valid = False
                    group_failures.extend(child_failures)
            if valid:
                winners.append(index)
            else:
                failed_paths.append({
                    "memory_id": memory_id, "path_index": index,
                    "reasons": tuple(dict.fromkeys(
                        (issue["reason"], issue["memory_id"]) for issue in group_failures
                    )),
                })
                all_failures.extend(group_failures)

        if memory_id == str(root_id):
            selected_root_paths.extend(winners)
        return bool(winners), all_failures if not winners else []

    valid, failures = check(
        str(root_id), dict(root_row), tuple(dict(item) for item in root_evidence),
        (str(root_id),), 0,
    )
    # 即使某一条替代路径存活，任何被访问路径中的越权、循环或未覆盖节点仍必须 fail closed。
    errors = fatalities + (failures if not valid else [])
    unique = {}
    for issue in errors:
        marker = (issue["reason"], issue["memory_id"], tuple(issue.get("path", ())))
        unique[marker] = issue
    return {
        "stale_sources": list(unique.values()),
        "checked_memories": len(cache),
        "checked_edges": checked_edges,
        "valid_paths": tuple(selected_root_paths) if not errors else (),
        "failed_paths": failed_paths[:32],
    }
