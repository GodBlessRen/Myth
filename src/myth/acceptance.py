"""Exact Agent 的固定验收与有界上下文纯函数。
冻结基线字节和验收规则后独立核对候选及证据；模型的完成请求不授予交付资格。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any, Iterable

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


# 来源证据片段的用途分类；分类只帮助验证/展示，不改变来源事实。
class EvidenceKind(StrEnum):
    # FAILURE：直接描述失败事实的来源片段。
    FAILURE = "failure"
    # SUCCESS：直接描述成功事实的来源片段。
    SUCCESS = "success"
    # TARGET：定位关键对象或位置的来源片段。
    TARGET = "target"
    # WARNING：需要保留但不自动判失败的来源片段。
    WARNING = "warning"
    # SUMMARY：来源中原本就存在的摘要片段，不是模型新写的总结。
    SUMMARY = "summary"


# 一条必须逐字存在于固定来源中的证据片段。
@dataclass(frozen=True)
class EvidenceQuote:
    # kind：证据用途分类，不授予额外可信度。
    kind: EvidenceKind
    # quote：必须能在 source text 中逐字定位的原文。
    quote: str

    # 构造时限制空引用和异常长引用；真正绑定来源仍由 validate_source_evidence 完成。
    def __post_init__(self) -> None:
        if not self.quote:
            raise ValueError("evidence quote must not be empty")
        if len(self.quote) > 2000:
            raise ValueError("evidence quote exceeds 2000 characters")


# 摘要/压缩候选携带的来源证据；通过验证前不能替代原始 Artifact/Observation。
@dataclass(frozen=True)
class SourceEvidence:
    # source_ref：原始来源稳定引用。
    source_ref: str
    # source_digest：原始 UTF-8 文本 SHA-256。
    source_digest: str
    # status：候选结构化状态；最终仍受 source digest 和 quote 约束。
    status: str
    # evidence：逐字来源片段集合。
    evidence: tuple[EvidenceQuote, ...]
    # summary：便于阅读的候选摘要；本身不产生可信度。
    summary: str = ""

    # 构造时只校验身份形状；内容真实性由 validate_source_evidence 决定。
    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")
        if len(self.source_digest) != 64:
            raise ValueError("source_digest must be a SHA-256 hex digest")


# 来源证据验证结果；失败保持原因码供恢复，不放松原始验证条件。
@dataclass(frozen=True)
class EvidenceCheck:
    # accepted：摘要候选是否完整绑定到固定来源。
    accepted: bool
    # reason_code：稳定机器原因码。
    reason_code: str
    # rejected_quotes：无法逐字在来源中定位的候选片段。
    rejected_quotes: tuple[str, ...] = ()

    # 转为只读投影；不修改来源或候选内容。
    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "rejected_quotes": list(self.rejected_quotes),
        }


# 对原始 UTF-8 文本计算固定来源身份。
def source_digest(source_text: str) -> str:
    return sha256(source_text.encode("utf-8")).hexdigest()


# 验证摘要/压缩候选的 source digest 与逐字引用；失败时调用方继续使用原始来源。
def validate_source_evidence(
    source_text: str,
    candidate: SourceEvidence,
    *,
    require_failure_evidence: bool = False,
) -> EvidenceCheck:
    if source_digest(source_text) != candidate.source_digest:
        return EvidenceCheck(False, "source_digest_mismatch")
    rejected = tuple(
        item.quote for item in candidate.evidence if item.quote not in source_text
    )
    if rejected:
        return EvidenceCheck(False, "unverifiable_quote", rejected)
    if require_failure_evidence and candidate.status.upper() in {
        "FAILED",
        "FAILURE",
        "ERROR",
    }:
        if not any(
            item.kind in {EvidenceKind.FAILURE, EvidenceKind.TARGET}
            for item in candidate.evidence
        ):
            return EvidenceCheck(False, "missing_failure_evidence")
    return EvidenceCheck(True, "verified")


# 一组候选只有全部绑定同一固定来源时才可继续；任一失败即返回 None，保留原始来源。
def validated_source_evidence_or_none(
    source_text: str,
    candidates: Iterable[SourceEvidence],
) -> tuple[SourceEvidence, ...] | None:
    values = tuple(candidates)
    if any(not validate_source_evidence(source_text, item).accepted for item in values):
        return None
    return values
