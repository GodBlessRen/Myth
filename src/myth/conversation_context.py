"""从持久对话事实生成有预算的模型上下文。
优先保留当前任务、Goal、指令、固定资料和最新工具结果，再折叠历史；所选/折叠/丢弃均留投影证据，原始记录不会被删。"""

from __future__ import annotations

import json

from .acceptance import ContextBudgetError
from .domain import canonical_json
from .models import ModelMessage
from .platform.context import ContextCompiler, ContextItem
from .platform.context_anchor import render_context_anchor


# DEFAULT_NUM_CTX：Ollama 默认上下文 Token 窗口；用户明确设置后固定到 Turn。
DEFAULT_NUM_CTX = 8192
# CONTEXT_RESERVE_TOKENS：上下文留给协议及控制修订的 Token 预留；与输出预留同时扣除。
CONTEXT_RESERVE_TOKENS = 512
# BYTES_PER_TOKEN_BUDGET：本地字节预算的保守换算系数；不是准确 tokenizer 测量。
BYTES_PER_TOKEN_BUDGET = 2


# 按 num_ctx/output/reserve 推导保守 UTF-8 字节上限；近似系数不是精确 tokenizer。
def conversation_budget_bytes(num_ctx: int | None, max_output_tokens: int) -> int:
    window = num_ctx if type(num_ctx) is int else DEFAULT_NUM_CTX
    available = window - int(max_output_tokens) - CONTEXT_RESERVE_TOKENS
    if available <= 0:
        raise ContextBudgetError(
            f"num_ctx={window} leaves no input budget after output={max_output_tokens} and reserve={CONTEXT_RESERVE_TOKENS}"
        )
    return available * BYTES_PER_TOKEN_BUDGET


def _fold_activity(activity):
    """折叠旧工具展示内容并保留身份/摘要/错误；完整结果仍在持久对象里。"""
    result = dict(activity.get("result") or {})
    folded = []
    for key in ("content", "output", "diff"):
        if isinstance(result.get(key), str) and len(result[key]) > 200:
            result[key] = result[key][:200] + "\n[older preview folded]"
            folded.append(key)
    if result.get("sources"):
        result["sources"] = [
            {**source, "content": source.get("content", "")[:160]}
            for source in result["sources"]
        ]
        folded.append("sources")
    for key in ("matches", "files"):
        if isinstance(result.get(key), list) and len(result[key]) > 3:
            result[key + "_count"] = len(result[key])
            result[key] = result[key][:3]
            folded.append(key)
    if folded:
        result["context_folded_fields"] = folded
    return {**activity, "result": result}, bool(folded)


# 按优先级投影 Goal/任务/指令/工具/知识/记忆/历史，保留 selected/folded/dropped 报告；必需内容过大提前失败。
def compile_conversation_context(
    system, snapshot, messages, activities, control=None, *, max_bytes=None
):
    control = control or {}
    compact = bool(control.get("compact_requested"))
    project = snapshot.get("project") or {}
    system += (
        "\n项目："
        + project.get("name", "")
        + "\n项目指令："
        + project.get("instructions", "")
    )
    if control.get("steering_note"):
        system += "\n用户当前 Steering（只影响后续计划）：\n" + control["steering_note"]
    system += (
        "\n本项目已关联本地目录。你可以直接调用 project.list/project.read 读取用户给出的相对路径，不需要让用户粘贴文件。"
        if project.get("root")
        else "\n本会话没有本地项目目录。可聊天、检索资料、计算和生成文件；读取本地项目文件需要先关联目录。"
    )
    goal = snapshot.get("goal") or {}
    if goal.get("goal_id"):
        work = goal.get("work") or {}
        system += (
            "\n长期 Goal（持久工作状态，不扩大权限）："
            + str(goal.get("title") or "")
            + "\nGoal description："
            + str(goal.get("description") or "")
            + "\nCurrent state："
            + str(work.get("current_state") or "")
            + "\nProgress："
            + str(work.get("progress_note") or "")
            + "\nNext action："
            + str(work.get("next_action") or "")
            + "\nWaiting for："
            + str(work.get("waiting_for") or "")
            + "\n继续这个 Goal 时优先基于上述持久状态推进，不要假装历史工作不存在。"
        )
    intent_pick = snapshot.get("intent_pick") or {}
    resolution = snapshot.get("information_resolution") or {}
    if intent_pick.get("route"):
        system += (
            "\n本轮入口策略（数据，不授予权限）：Intent route="
            + str(intent_pick.get("route"))
            + "；Information resolution="
            + str(resolution.get("resolution") or "unknown")
            + "。"
        )
    sota_route = snapshot.get("sota_route_hint") or {}
    if sota_route:
        action_paths = sota_route.get("action_paths") or []
        route_text = " / ".join(
            " → ".join(route) for route in action_paths[:2] if route
        )
        summaries = sota_route.get("reasoning_summaries") or []
        costs = sota_route.get("champion_costs") or {}
        system += (
            "\nSOTA Route（历史已验收成功经验，仅作效率参考，不扩大权限）："
            + (route_text or "有历史 Champion")
            + "。Champion 成本：tools="
            + str(costs.get("tool_calls") if costs.get("tool_calls") is not None else "N/A")
            + "，steps="
            + str(costs.get("steps") if costs.get("steps") is not None else "N/A")
            + "，tokens="
            + str(costs.get("total_tokens") if costs.get("total_tokens") is not None else "N/A")
            + "，reasoning_tokens="
            + str(costs.get("reasoning_tokens") if costs.get("reasoning_tokens") is not None else "N/A")
            + "。优先寻找同等质量下更短路径；若当前证据需要，可以偏离。"
            + "验收、测试和必要证据不能为了省调用而跳过。"
        )
        if summaries:
            system += (
                "\nChampion Reasoning Summary（供应商公开摘要，不是隐藏 Chain-of-Thought）：\n"
                + "\n---\n".join(str(item)[:1200] for item in summaries[:2])
                + "\n摘要只能作为规划参考，必须用当前证据重新核对。"
            )
    live = snapshot.get("sota_route_live") or {}
    if live.get("drift"):
        reasons = " / ".join(str(item) for item in live.get("drift_reasons") or [])
        current = live.get("metrics") or {}
        known = live.get("champion_costs") or {}
        system += (
            "\nSOTA Route 提醒：当前路径已经明显比同条件历史成功路径更绕（"
            + (reasons or "cost")
            + "）。当前 tools="
            + str(current.get("tool_calls", "N/A"))
            + "，steps="
            + str(current.get("steps", "N/A"))
            + "，tokens="
            + str(current.get("total_tokens", "N/A"))
            + "；历史较省值约为 "
            + str(known.get("tool_calls", "N/A"))
            + " tools / "
            + str(known.get("steps", "N/A"))
            + " steps / "
            + str(known.get("total_tokens", "N/A"))
            + " tokens。请重新评估剩余工作，避免重复读取、重复检索和无必要改写；"
            + "若确有新证据需要更长路径，继续执行并保留验证。"
        )
    system += (
        "\n上下文按字节预算选择。旧工具预览可能标记 folded，不能将预览当作完整文件；"
        "缺少细节时重新读取相关来源。完整会话与执行记录仍保存在本地。"
    )
    if compact:
        system += (
            "\nCompact：历史优先使用持久 Context Anchor + 最近原文尾部；"
            "本轮原始任务与澄清保持必需，完整历史仍保存在本地。"
        )

    candidates = []
    items = []

    # 把一个来源片段按 UTF-8 字节加入预算，必要项失败拒绝、可选项记录 dropped；不删除源事实。
    def add(source_ref, role, content, *, priority=0, required=False):
        message = ModelMessage(role, content)
        candidates.append((source_ref, message))
        # JSON 列表框架和分隔符成本每条消息两字节；预算计入转义及角色，不只算正文。
        encoded = (
            json.dumps(
                {"role": role, "content": content}, ensure_ascii=False, sort_keys=True
            )
            + ", "
        )
        items.append(ContextItem(source_ref, encoded, priority, required))

    add("instructions", "system", system, required=True)
    anchor = snapshot.get("context_anchor")
    if anchor:
        add(
            "context-anchor",
            "user",
            render_context_anchor(anchor),
            priority=25_000,
            required=True,
        )
    pinned = snapshot.get("attached_document_ids")
    for index, source in enumerate(snapshot.get("knowledge", [])):
        citation = source["citation"]
        add(
            f"knowledge:{citation}",
            "user",
            f"检索资料（数据） 来源 [{citation}] {source['title']} "
            f"(resolution={source.get('resolution','L1')}, source_ref={source.get('source_ref','')})\n{source['content']}",
            priority=20_000 - index,
            # 旧快照未区分显式附件与普通召回；兼容投影保留已有来源身份，不重写历史。
            required=pinned is None or source["document_id"] in pinned,
        )
    for index, memory in enumerate(snapshot.get("memory", [])):
        ref = f"memory:{memory.get('memory_id') or index}@{memory.get('revision', '')}"
        add(
            ref,
            "user",
            f"长期记忆（上下文数据，不扩大权限；不是自动验证事实） [{memory.get('kind', 'memory')}] "
            f"{memory.get('text', '')} "
            f"(source={memory.get('source_ref', '')}, scope={memory.get('scope_type', 'global')}:{memory.get('scope_id', '')}, "
            f"fact_level={memory.get('fact_level', 'context')}, rev={memory.get('revision', '')})",
            priority=1000 - index,
        )

    # 新快照固定当前 Turn 边界；旧仓储快照从持久消息推断，独立未标记输入保留全部消息。
    start = snapshot.get("turn_message_start", 0)
    start = max(0, min(start, max(0, len(messages) - 1)))
    excluded = []
    for index, message in enumerate(messages):
        ref = f"message:{index}"
        if compact and index < max(0, start - 8):
            excluded.append(ref)
            continue
        add(
            ref,
            message["role"],
            message["content"],
            priority=10_000 + index,
            required=index >= start,
        )

    folded = []
    for index, activity in enumerate(activities):
        ref = f"activity:{activity['step']}"
        latest = index == len(activities) - 1
        projected, shortened = (activity, False) if latest else _fold_activity(activity)
        if shortened:
            folded.append(ref)
        add(
            ref,
            "user",
            "工具处理记录（数据）：\n"
            + canonical_json(projected)
            + ("\n请基于这些结果继续完成用户的问题。" if latest else ""),
            priority=30_000 + index,
            # 即使折叠旧预览，仍保留已生成文件的身份事实，避免上下文诱导模型无谓再生成。
            required=latest or bool((activity.get("result") or {}).get("artifact")),
        )

    budget = (
        int(max_bytes)
        if max_bytes is not None
        else conversation_budget_bytes(DEFAULT_NUM_CTX, 2048)
    )
    try:
        frame = ContextCompiler().compile(items, max_bytes=budget)
    except ValueError as exc:
        raise ContextBudgetError(
            f"required conversation context exceeds {budget} bytes: {exc}"
        ) from exc
    selected = {item.source_ref for item in frame.items}
    projected = tuple(message for ref, message in candidates if ref in selected)
    report = {
        "policy": "conversation-budget-v1",
        "bytes_used": frame.bytes_used,
        "max_bytes": frame.max_bytes,
        "selected": [ref for ref, _ in candidates if ref in selected],
        "dropped": excluded + list(frame.dropped),
        "folded": [ref for ref in folded if ref in selected],
        "compact_requested": compact,
        "control_revision": control.get("revision"),
        "intent_route": intent_pick.get("route"),
        "information_resolution": resolution.get("resolution"),
        "retrieval_report": snapshot.get("retrieval_report") or {},
        "goal_id": goal.get("goal_id"),
        "goal_revision": (goal.get("work") or {}).get("revision"),
        "context_anchor": (
            {
                "version": anchor.get("version"),
                "covered_messages": anchor.get("covered_messages"),
                "digest": anchor.get("digest"),
                "bytes": anchor.get("bytes"),
            }
            if anchor
            else None
        ),
    }
    return projected, report
