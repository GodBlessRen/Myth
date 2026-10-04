"""可持久的增量 Context Anchor。
旧消息只做确定性抽取并增量合并，最近尾部继续保留原文；Anchor 是派生投影，不是 Memory、权限或验证事实。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# 把文本按 UTF-8 字节安全裁剪；裁剪只作用派生 Anchor，不改写原始消息。
def _clip_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


# 对单条历史消息做确定性抽取；保留开头与结尾，避免把整个长消息再次塞回 Context。
def _message_excerpt(index: int, message: dict[str, Any]) -> str:
    role = str(message.get("role") or "unknown")
    content = str(message.get("content") or "").strip()
    if len(content.encode("utf-8")) > 700:
        head = _clip_bytes(content, 420)
        tail_raw = content.encode("utf-8")[-220:]
        tail = tail_raw.decode("utf-8", errors="ignore")
        content = head + " … " + tail
    return f"[{index}] {role}: {content}"


# Anchor 超预算时保留最早约束与最近变化；中段折叠明确标记，不伪装完整历史。
def _bound_summary(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = "\n… [middle of context anchor folded] …\n"
    marker_bytes = len(marker.encode("utf-8"))
    head_limit = max(256, (max_bytes - marker_bytes) // 3)
    tail_limit = max(256, max_bytes - marker_bytes - head_limit)
    head = _clip_bytes(text, head_limit)
    tail = raw[-tail_limit:].decode("utf-8", errors="ignore")
    return head + marker + tail


# 增量合并此前 Anchor 与新跨过阈值的消息；不会重新总结已有 Anchor，lineage_digest 绑定新增原文。
def build_context_anchor(
    previous: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    *,
    cover_count: int,
    max_bytes: int = 6000,
) -> dict[str, Any] | None:
    previous = dict(previous or {})
    already = max(0, int(previous.get("covered_messages") or 0))
    target = max(already, min(int(cover_count), len(messages)))
    if target <= already:
        return previous or None

    additions = messages[already:target]
    lines = [_message_excerpt(index, message) for index, message in enumerate(additions, start=already)]
    old_summary = str(previous.get("summary") or "").strip()
    merged = "\n".join(part for part in (old_summary, *lines) if part)
    summary = _bound_summary(merged, max_bytes)

    lineage = hashlib.sha256()
    prior_digest = str(previous.get("lineage_digest") or "")
    lineage.update(prior_digest.encode("ascii", errors="ignore"))
    lineage.update(
        json.dumps(additions, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    lineage_digest = lineage.hexdigest()
    anchor_digest = hashlib.sha256(
        json.dumps(
            {"covered_messages": target, "summary": summary, "lineage_digest": lineage_digest},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "version": "extractive-anchor-v1",
        "covered_messages": target,
        "summary": summary,
        "lineage_digest": lineage_digest,
        "digest": anchor_digest,
        "bytes": len(summary.encode("utf-8")),
    }


# 将 Anchor 投影给模型；明确它是有损派生导航，关键事实仍须回到持久来源/工具证据核对。
def render_context_anchor(anchor: dict[str, Any]) -> str:
    return (
        "历史 Context Anchor（确定性抽取的有损派生投影，不扩大权限、不等于验证事实）：\n"
        + str(anchor.get("summary") or "")
        + "\n需要关键细节时重新读取持久来源；最近消息仍以原文提供。"
    )
