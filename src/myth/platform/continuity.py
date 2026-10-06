"""Conversation 连续性的纯判定策略。
它只根据持久消息身份、固定设置和 Current Facts 版本决定派生上下文能否复用；
不调用模型、不读取网络、不拥有 Session/Memory 状态，也不执行恢复动作。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..domain import digest_json


CONTINUITY_POLICY = "conversation-continuity-v1"
CURRENT_FACTS_POLICY = "current-facts-v1"


def message_digest(role: object, content: object) -> str:
    """绑定消息角色和正文；同一持久消息身份不能静默替换内容。"""
    return digest_json({"role": str(role or ""), "content": str(content or "")})


def history_digest(
    messages: Sequence[Mapping[str, Any]], count: int | None = None
) -> str:
    """只保存历史身份/正文摘要，不把消息正文复制进 Continuity 状态。"""
    limit = len(messages) if count is None else max(0, min(int(count), len(messages)))
    rows = [
        {
            "id": message.get("id"),
            "run_id": message.get("run_id"),
            "role": message.get("role"),
            "content_digest": message_digest(
                message.get("role"), message.get("content")
            ),
        }
        for message in messages[:limit]
    ]
    return digest_json(rows)


# 用写入时正文摘要复核尾部消息；缺失/不一致都不能证明是同一历史，必须 fail closed。
def _message_integrity(message: Mapping[str, Any]) -> bool:
    metadata = message.get("metadata")
    expected = metadata.get("content_digest") if isinstance(metadata, Mapping) else None
    return isinstance(expected, str) and expected == message_digest(
        message.get("role"), message.get("content")
    )


# Project 指令属于模型语义环境，只绑定摘要；目录/指令正文仍由 Project 状态所有者保存。
def _project_digest(project: Mapping[str, Any] | None) -> str | None:
    if not project:
        return None
    return digest_json(
        {
            "id": project.get("id"),
            "name": project.get("name"),
            "description": project.get("description"),
            "instructions": project.get("instructions"),
            "root": project.get("root"),
        }
    )


def continuity_binding(
    settings: Mapping[str, Any],
    project: Mapping[str, Any] | None,
    current_facts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """绑定影响历史投影兼容性的环境；query ranking 和普通 recall 不参与。"""
    facts = dict(current_facts or {})
    return {
        "provider": str(settings.get("provider") or ""),
        "provider_config": digest_json({"ollama_url": settings.get("ollama_url")}),
        "model": str(settings.get("model") or ""),
        "context_window": settings.get("num_ctx"),
        "project": _project_digest(project),
        "current_facts": facts.get("digest"),
    }


_BINDING_REASONS = (
    ("provider", "provider_changed"),
    ("provider_config", "provider_config_changed"),
    ("model", "model_changed"),
    ("context_window", "context_window_changed"),
    ("project", "project_changed"),
    ("current_facts", "current_facts_changed"),
)


# 按稳定优先级返回首个环境变化原因；顺序固定使日志、评测与恢复诊断可重复。
def _binding_change_reason(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> str | None:
    if any(key not in previous for key, _ in _BINDING_REASONS):
        return "continuity_baseline_missing"
    for key, reason in _BINDING_REASONS:
        if previous.get(key) != current.get(key):
            return reason
    return None


# 统一构造 metadata-only 计划；计划描述 Context 复用，不携带执行回调或外部副作用。
def _plan(
    *,
    action: str,
    reason: str,
    epoch: int,
    history: Sequence[Mapping[str, Any]],
    binding: Mapping[str, Any],
    current_facts: Mapping[str, Any] | None,
    tail_count: int,
    anchor_reuse: bool,
) -> dict[str, Any]:
    facts = dict(current_facts or {})
    return {
        "policy": CONTINUITY_POLICY,
        "action": action,
        "reason": reason,
        "epoch": max(1, int(epoch)),
        "history_count": len(history),
        "history_digest": history_digest(history),
        "tail_count": max(0, int(tail_count)),
        "binding": dict(binding),
        "binding_digest": digest_json(binding),
        "current_facts": {
            "policy": facts.get("policy") or CURRENT_FACTS_POLICY,
            "count": max(0, int(facts.get("count") or 0)),
            "digest": facts.get("digest"),
        },
        "anchor_reuse": bool(anchor_reuse),
    }


def plan_conversation_continuity(
    *,
    previous_turn: Mapping[str, Any] | None,
    history: Sequence[Mapping[str, Any]],
    settings: Mapping[str, Any],
    project: Mapping[str, Any] | None,
    current_facts: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """决定派生历史能否复用；rebuild 不删除历史，也不授予任何效果重放权。"""
    # 先核对上一Turn终态、策略版本和配置/当前事实绑定，再核对历史前缀摘要。
    # 任一绑定或前缀变化都重建epoch；只有完整匹配才允许追加历史并复用派生anchor。
    messages = list(history)
    binding = continuity_binding(settings, project, current_facts)
    if previous_turn is None:
        return _plan(
            action="new",
            reason="first_turn",
            epoch=1,
            history=messages,
            binding=binding,
            current_facts=current_facts,
            tail_count=len(messages),
            anchor_reuse=False,
        )

    snapshot = previous_turn.get("snapshot")
    previous = snapshot.get("continuity") if isinstance(snapshot, Mapping) else None
    previous_epoch = int(previous.get("epoch") or 0) if isinstance(previous, Mapping) else 0
    rebuild_epoch = max(1, previous_epoch + 1)

    if previous_turn.get("status") != "COMPLETED":
        return _plan(
            action="rebuild", reason="previous_turn_incomplete",
            epoch=rebuild_epoch, history=messages, binding=binding,
            current_facts=current_facts, tail_count=len(messages), anchor_reuse=False,
        )
    if (
        not isinstance(previous, Mapping)
        or previous.get("policy") != CONTINUITY_POLICY
        or not isinstance(previous.get("binding"), Mapping)
        or type(previous.get("history_count")) is not int
        or not isinstance(previous.get("history_digest"), str)
    ):
        return _plan(
            action="rebuild", reason="continuity_baseline_missing",
            epoch=rebuild_epoch, history=messages, binding=binding,
            current_facts=current_facts, tail_count=len(messages), anchor_reuse=False,
        )

    reason = _binding_change_reason(previous["binding"], binding)
    if reason:
        return _plan(
            action="rebuild", reason=reason, epoch=rebuild_epoch,
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=max(0, len(messages) - int(previous["history_count"])),
            anchor_reuse=False,
        )

    prior_count = int(previous["history_count"])
    if prior_count < 0 or prior_count > len(messages):
        return _plan(
            action="rebuild", reason="history_truncated", epoch=rebuild_epoch,
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=0, anchor_reuse=False,
        )
    if history_digest(messages, prior_count) != previous["history_digest"]:
        return _plan(
            action="rebuild", reason="history_changed", epoch=rebuild_epoch,
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=len(messages) - prior_count, anchor_reuse=False,
        )

    tail = messages[prior_count:]
    if not tail:
        return _plan(
            action="rebuild", reason="history_gap", epoch=rebuild_epoch,
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=0, anchor_reuse=False,
        )
    if any(not _message_integrity(message) for message in tail):
        return _plan(
            action="rebuild", reason="history_message_changed", epoch=rebuild_epoch,
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=len(tail), anchor_reuse=False,
        )

    previous_run_id = previous_turn.get("run_id")
    tail_run_ids = [message.get("run_id") for message in tail]
    if previous_run_id and all(run_id == previous_run_id for run_id in tail_run_ids):
        return _plan(
            action="resume", reason="direct_continuation", epoch=max(1, previous_epoch),
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=len(tail), anchor_reuse=True,
        )
    if previous_run_id and previous_run_id in tail_run_ids:
        return _plan(
            action="catchup", reason="intervening_messages", epoch=max(1, previous_epoch),
            history=messages, binding=binding, current_facts=current_facts,
            tail_count=len(tail), anchor_reuse=True,
        )
    return _plan(
        action="rebuild", reason="branch_or_history_gap", epoch=rebuild_epoch,
        history=messages, binding=binding, current_facts=current_facts,
        tail_count=len(tail), anchor_reuse=False,
    )
