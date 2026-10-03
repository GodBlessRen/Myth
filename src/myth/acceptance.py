"""Exact Agent 的固定验收与有界上下文纯函数。
冻结基线字节和验收规则后独立核对候选及证据；模型的完成请求不授予交付资格。"""

from __future__ import annotations

from typing import Any

from .domain import Verdict, canonical_json, digest_json, exact_patch, sha256_bytes


class ContextBudgetError(ValueError):
    """必需上下文超出本地字节预算；在调用模型前拒绝，字节预算不是准确 Token 计数。"""


def freeze_acceptance(
    files: dict[str, bytes], rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """根据入口固定规则计算所有文件期望摘要；未修改文件也必须保持基线，模型不得改写此合同。"""
    expected = dict(files)
    normalized = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {
            "path",
            "old_text",
            "new_text",
            "expected_count",
        }:
            raise ValueError(
                "each acceptance rule requires path, old_text, new_text, expected_count"
            )
        path = rule["path"]
        if path not in expected:
            raise PermissionError("acceptance path is outside allowed_files")
        expected[path] = exact_patch(
            expected[path], rule["old_text"], rule["new_text"], rule["expected_count"]
        ).after
        normalized.append(dict(rule))
    manifest = {
        "version": "exact-goal-v1",
        "rules": normalized,
        "files": [
            {
                "path": path,
                "before_digest": sha256_bytes(data),
                "expected_digest": sha256_bytes(expected[path]),
            }
            for path, data in files.items()
        ],
    }
    return {**manifest, "digest": digest_json(manifest)}


def verify_goal(
    manifest: dict[str, Any],
    current: dict[str, str],
    evidence: dict[str, dict[str, Any]],
    cited: tuple[str, ...],
    remaining: tuple[str, ...],
) -> tuple[Verdict, str]:
    """独立检查全部候选摘要、已成功收据、引用覆盖和剩余项；证据不足返回 INCONCLUSIVE。"""
    if not manifest.get("rules"):
        return (
            Verdict.INCONCLUSIVE,
            "no trusted goal acceptance rules were fixed at submission",
        )
    if remaining:
        return Verdict.INCONCLUSIVE, "model still lists unfinished work"
    if (
        not cited
        or len(cited) != len(set(cited))
        or any(ref not in evidence for ref in cited)
    ):
        return (
            Verdict.INCONCLUSIVE,
            "completion requires unique durable evidence from this run",
        )
    for ref in cited:
        item = evidence[ref]
        if item["attempt_state"] != "RESOLVED" or item["outcome"] != "SUCCEEDED":
            return Verdict.INCONCLUSIVE, "cited tool outcome is not durably successful"
        if current.get(item["source_file"]) != item["after_digest"]:
            return (
                Verdict.INCONCLUSIVE,
                "cited evidence does not match the current candidate",
            )
    for item in manifest["files"]:
        if current.get(item["path"]) != item["expected_digest"]:
            return (
                Verdict.FAIL,
                "complete candidate differs from the fixed goal acceptance",
            )
    changed = {
        item["path"]
        for item in manifest["files"]
        if item["before_digest"] != item["expected_digest"]
    }
    covered = {evidence[ref]["source_file"] for ref in cited}
    if not changed.issubset(covered):
        return (
            Verdict.INCONCLUSIVE,
            "completion evidence does not cover every changed file",
        )
    return (
        Verdict.PASS,
        "all fixed goal bytes, preserved files and durable evidence agree",
    )


def compile_context(
    notes: list[dict[str, Any]], manifest: dict[str, Any], *, max_bytes: int = 32_768
) -> str:
    """压缩 Exact 用例的展示投影，保留固定验收、用户约束及证据引用；必需信息超字节上限时拒绝调用。"""
    history = []
    latest_tool = next(
        (n["sequence"] for n in reversed(notes) if n["kind"] == "tool_result"), None
    )
    for note in notes[-24:]:
        item = {
            "sequence": note["sequence"],
            "kind": note["kind"],
            "payload": dict(note["payload"]),
        }
        if "preview" in item["payload"] and note["sequence"] != latest_tool:
            item["payload"]["preview"] = item["payload"]["preview"][:240]
            item["payload"]["preview_folded"] = True
        history.append(item)
    pinned = [
        n
        for n in notes
        if n["kind"] in {"user", "verification_rejected", "tool_rejected"}
    ]
    evidence = [
        n["payload"]
        for n in notes
        if n["kind"] == "tool_result" and n["payload"].get("evidence_ref")
    ]
    value = {
        "acceptance": manifest,
        "history": history,
        "constraints": [{"kind": n["kind"], "payload": n["payload"]} for n in pinned],
        "latest_tool_result": next(
            (n["payload"] for n in reversed(notes) if n["kind"] == "tool_result"), None
        ),
        "tool_evidence": [
            {k: v for k, v in p.items() if k != "preview"} for p in evidence
        ],
    }
    encoded = canonical_json(value)
    while len(encoded.encode("utf-8")) > max_bytes and history:
        history.pop(0)
        encoded = canonical_json(value)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ContextBudgetError(
            f"required context exceeds the {max_bytes}-byte budget; split the task"
        )
    return encoded
