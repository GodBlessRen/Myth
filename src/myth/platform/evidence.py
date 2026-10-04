"""Evidence-bound transformation 的纯验证合同。
LLM/Reducer 生成的自然语言只是候选投影；只有能绑定到固定 source digest 的逐字证据才可成为已验证 Receipt。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Iterable


# 证据类型只表达来源用途，不把模型判断升级为事实。
class EvidenceKind(StrEnum):
    # FAILURE：直接描述失败事实的来源片段。
    FAILURE = "failure"
    # SUCCESS：直接描述成功事实的来源片段。
    SUCCESS = "success"
    # TARGET：定位到关键对象/位置的来源片段。
    TARGET = "target"
    # WARNING：非致命但应保留的警告证据。
    WARNING = "warning"
    # SUMMARY：来源中的原始摘要片段，不是模型新生成的总结。
    SUMMARY = "summary"


# 一条必须逐字存在于固定来源中的证据引用；kind 只帮助下游解释用途。
@dataclass(frozen=True)
class EvidenceQuote:
    # kind：证据用途分类，不改变来源事实。
    kind: EvidenceKind
    # quote：必须能在 source text 中逐字找到的原文。
    quote: str

    def __post_init__(self) -> None:
        if not self.quote:
            raise ValueError("evidence quote must not be empty")
        if len(self.quote) > 2000:
            raise ValueError("evidence quote exceeds 2000 characters")


# 非可信 Transformer 的候选 Receipt；通过验证前不能替代 source artifact。
@dataclass(frozen=True)
class EvidenceReceipt:
    # source_ref：原始证据对象的稳定引用。
    source_ref: str
    # source_digest：原始 UTF-8 文本的 SHA-256 身份。
    source_digest: str
    # status：候选对来源状态的结构化描述；最终仍需证据约束。
    status: str
    # evidence：逐字证据集合。
    evidence: tuple[EvidenceQuote, ...]
    # summary：可读摘要；本身不产生可信度。
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")
        if len(self.source_digest) != 64:
            raise ValueError("source_digest must be a SHA-256 hex digest")


# Receipt 验证结果；拒绝原因可用于有界 repair，但不能放松后续同一验证器。
@dataclass(frozen=True)
class EvidenceValidation:
    # accepted：source digest 与全部必要 quote 是否通过固定验证。
    accepted: bool
    # reason_code：稳定拒绝/通过原因码。
    reason_code: str
    # rejected_quotes：未能逐字绑定来源的候选 quote。
    rejected_quotes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "rejected_quotes": list(self.rejected_quotes),
        }


# 对源文本计算固定身份；转换器无权自己声明另一份 source digest。
def evidence_digest(source_text: str) -> str:
    return sha256(source_text.encode("utf-8")).hexdigest()


# 逐字验证 Receipt；任何 quote 漂移都拒绝整个候选，调用方应 fail-open 使用原始 source。
def validate_evidence_receipt(
    source_text: str,
    receipt: EvidenceReceipt,
    *,
    require_failure_evidence: bool = False,
) -> EvidenceValidation:
    if evidence_digest(source_text) != receipt.source_digest:
        return EvidenceValidation(False, "source_digest_mismatch")
    rejected = tuple(
        item.quote for item in receipt.evidence if item.quote not in source_text
    )
    if rejected:
        return EvidenceValidation(False, "unverifiable_quote", rejected)
    if require_failure_evidence and receipt.status.upper() in {"FAILED", "FAILURE", "ERROR"}:
        if not any(
            item.kind in {EvidenceKind.FAILURE, EvidenceKind.TARGET}
            for item in receipt.evidence
        ):
            return EvidenceValidation(False, "missing_failure_evidence")
    return EvidenceValidation(True, "verified")


# 只在全部候选都通过同一固定源验证时返回 Receipt；否则返回空值，让调用方使用原始来源。
def verified_receipts_or_none(
    source_text: str,
    receipts: Iterable[EvidenceReceipt],
) -> tuple[EvidenceReceipt, ...] | None:
    values = tuple(receipts)
    if any(not validate_evidence_receipt(source_text, item).accepted for item in values):
        return None
    return values
