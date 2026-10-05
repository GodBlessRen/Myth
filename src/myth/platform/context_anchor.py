"""可持久的增量 Context Anchor。
旧消息只做确定性抽取并增量合并，最近尾部继续保留原文；Anchor 是派生投影，不是 Memory、权限或验证事实。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# 只裁剪派生展示字节；原始消息保持不变，避免 Context 预算操作反向改写持久事实。
def _clip_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


# 对单条历史做确定性摘录；保留首尾是为了可导航，不能把摘录冒充完整原文。
def _message_excerpt(index: int, message: dict[str, Any]) -> str:
    role = str(message.get("role") or "unknown")
    content = str(message.get("content") or "").strip()
    if len(content.encode("utf-8")) > 700:
        head = _clip_bytes(content, 420)
        tail = content.encode("utf-8")[-220:].decode("utf-8", errors="ignore")
        content = head + " … " + tail
    return f"[{index}] {role}: {content}"


# Anchor 超预算时只折叠派生中段并明确标记；静默截断会制造“历史完整”的假象。
def _bound_summary(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = "\n… [middle of context anchor folded] …\n"
    marker_bytes = len(marker.encode("utf-8"))
    head_limit = max(256, (max_bytes - marker_bytes) // 3)
    tail_limit = max(256, max_bytes - marker_bytes - head_limit)
    return (
        _clip_bytes(text, head_limit)
        + marker
        + raw[-tail_limit:].decode("utf-8", errors="ignore")
    )


def context_anchor_source_digest(
    messages: list[dict[str, Any]], cover_count: int
) -> str:
    """重新摘要真实 covered prefix；派生 Anchor 不能只相信自己的旧摘要。"""
    target = max(0, min(int(cover_count), len(messages)))
    source = [
        {
            "role": str(message.get("role") or "unknown"),
            "content": str(message.get("content") or ""),
        }
        for message in messages[:target]
    ]
    return hashlib.sha256(
        json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def context_anchor_reusable(
    previous: dict[str, Any] | None, messages: list[dict[str, Any]]
) -> bool:
    """只有版本、覆盖范围、原始来源摘要都匹配时才允许增量复用。"""
    if not isinstance(previous, dict) or previous.get("version") != "extractive-anchor-v2":
        return False
    covered = previous.get("covered_messages")
    if type(covered) is not int or covered < 0 or covered > len(messages):
        return False
    source_digest = previous.get("source_digest")
    return isinstance(source_digest, str) and source_digest == context_anchor_source_digest(
        messages, covered
    )


def build_context_anchor(
    previous: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    *,
    cover_count: int,
    max_bytes: int = 6000,
) -> dict[str, Any] | None:
    """增量推进 Anchor；来源失配时从真实历史重建，不能延续陈旧摘要。"""
    previous = dict(previous or {})
    if previous and not context_anchor_reusable(previous, messages):
        previous = {}

    already = max(0, int(previous.get("covered_messages") or 0))
    target = max(already, min(int(cover_count), len(messages)))
    if target <= already:
        return previous or None

    additions = messages[already:target]
    lines = [
        _message_excerpt(index, message)
        for index, message in enumerate(additions, start=already)
    ]
    old_summary = str(previous.get("summary") or "").strip()
    summary = _bound_summary(
        "\n".join(part for part in (old_summary, *lines) if part),
        max_bytes,
    )

    lineage = hashlib.sha256()
    lineage.update(
        str(previous.get("lineage_digest") or "").encode("ascii", errors="ignore")
    )
    lineage.update(
        json.dumps(
            additions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    lineage_digest = lineage.hexdigest()
    source_digest = context_anchor_source_digest(messages, target)
    anchor_digest = hashlib.sha256(
        json.dumps(
            {
                "covered_messages": target,
                "summary": summary,
                "lineage_digest": lineage_digest,
                "source_digest": source_digest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "version": "extractive-anchor-v2",
        "covered_messages": target,
        "summary": summary,
        "lineage_digest": lineage_digest,
        "source_digest": source_digest,
        "digest": anchor_digest,
        "bytes": len(summary.encode("utf-8")),
    }


# 投影给模型时明确 Anchor 是有损导航而非事实 authority；关键细节仍须回持久来源核对。
def render_context_anchor(anchor: dict[str, Any]) -> str:
    return (
        "历史 Context Anchor（来源摘要已校验的有损派生投影，不扩大权限、不等于验证事实）：\n"
        + str(anchor.get("summary") or "")
        + "\n需要关键细节时重新读取持久来源；最近消息仍以原文提供。"
    )
