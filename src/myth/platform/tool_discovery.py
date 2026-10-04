"""Conversation Tool 的渐进披露纯函数。
工具发现只改变下一步模型可见目录；真正执行仍须 Capability admission、Ticket 与具体适配器校验。"""

from __future__ import annotations

import re
from typing import Any


# 常用能力默认可见；专门 Git/Diff 工具延迟加载，避免整个目录长期占用 Prompt。
DEFAULT_VISIBLE_TOOL_IDS = (
    "knowledge.search",
    "knowledge.resolve",
    "memory.search",
    "memory.timeline",
    "memory.resolve",
    "project.list",
    "project.read",
    "observation.read",
    "project.search",
    "git.status",
    "git.diff",
    "artifact.write",
    "project.patch_exact",
    "test.run",
    "math.calculate",
    "agent.delegate",
    "tool.search",
    "tool.describe",
)

# 目录小于等于该规模时无需延迟加载；当前目录超过阈值后才启用渐进披露。
DEFERRED_LOADING_THRESHOLD = 12


# 读取已有 durable activities，把已实际使用/搜索/描述过的能力加入后续可见集合。
def visible_tool_ids(
    catalog: dict[str, Any],
    activities: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    ordered = tuple(catalog)
    if len(ordered) <= DEFERRED_LOADING_THRESHOLD:
        return ordered

    visible = {tool_id for tool_id in DEFAULT_VISIBLE_TOOL_IDS if tool_id in catalog}
    for activity in activities or ():
        decision = activity.get("decision") or {}
        result = activity.get("result") or {}
        capability = decision.get("capability_id")
        # 只有真正成功观察到的能力才因“已使用”保持可见；请求隐藏能力后被拒绝不能绕过 discovery。
        if (
            capability in catalog
            and result
            and not result.get("error")
            and not result.get("failure")
        ):
            visible.add(capability)
        for match in result.get("matches") or []:
            if isinstance(match, dict) and match.get("capability_id") in catalog:
                visible.add(match["capability_id"])
        described = result.get("described_tool")
        if described in catalog:
            visible.add(described)
    return tuple(tool_id for tool_id in ordered if tool_id in visible)


# 以稳定词面分数搜索工具身份/说明/参数名；这是目录导航，不是语义授权或 Information Gain。
def search_tools(
    catalog: dict[str, Any],
    descriptions: dict[str, str],
    query: str,
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    text = str(query or "").strip().lower()
    if not text or len(text) > 200:
        raise ValueError("tool.search query must contain 1-200 characters")
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError("tool.search limit must be 1-8")
    terms = set(re.findall(r"[a-z0-9_.-]+", text))
    ranked = []
    for index, (tool_id, arguments) in enumerate(catalog.items()):
        if tool_id in {"tool.search", "tool.describe"}:
            continue
        description = descriptions.get(tool_id, "")
        haystack = " ".join(
            [tool_id, description, *[str(key) for key in arguments]]
        ).lower()
        score = 0
        if text == tool_id.lower():
            score += 100
        if text in haystack:
            score += 20
        score += 5 * sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((-score, index, tool_id, description, arguments))
    ranked.sort()
    return [
        {
            "capability_id": tool_id,
            "description": description,
            "arguments": arguments,
        }
        for _, _, tool_id, description, arguments in ranked[:limit]
    ]


# 返回单个工具的完整目录说明；描述成功后该能力会通过 durable activity 在下一步变为可见。
def describe_tool(
    catalog: dict[str, Any],
    descriptions: dict[str, str],
    tool_id: str,
) -> dict[str, Any]:
    value = str(tool_id or "").strip()
    if value not in catalog or value in {"tool.search", "tool.describe"}:
        raise ValueError("tool.describe requires a known discoverable tool id")
    return {
        "described_tool": value,
        "description": descriptions.get(value, ""),
        "arguments": catalog[value],
    }
