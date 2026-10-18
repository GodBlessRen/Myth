"""受当前观察约束的有限动作候选：只生成模型可选的只读目标，不授予 Capability、Ticket 或新状态。

候选由同 Run 已结算的检索收据派生；真实来源版本与作用域仍由执行适配器重核。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..domain import digest_json

# 固定上界防止页面/检索结果过多时，选择题反而放大模型 Context。
MAX_ACTION_CANDIDATES = 8
# 仅开放已经具备权威来源校验的读路径；不能将写入或远程效果包进候选。
_SUPPORTED_SOURCES = frozenset({"knowledge.search", "memory.search", "memory.recall"})


# 一个候选只代表已观察目标的意图；身份绑定 Run、收据、原始版本与精确工具参数。
@dataclass(frozen=True)
class ActionCandidate:
    # candidate_id：内容寻址的选择身份；不是可复用的数组位置，也不是授权凭证。
    candidate_id: str
    # capability_id：最终进入现有准入、Hook、Ticket 与收据管线的真实工具身份。
    capability_id: str
    # arguments：Runtime 构造的不可变语义参数副本；传递时必须复制，不让模型补写目标。
    arguments: dict[str, Any]
    # source_decision_id：创建候选的同 Run 已结算 Tool Decision 身份。
    source_decision_id: str
    # source_ref：原始知识摘要或 Memory 修订引用，不由展示文本决定。
    source_ref: str
    # title：帮助模型辨别同名目标的短预览；它是可疑数据而非命令。
    title: str

    # 仅将有界身份与来源线索送入模型；完整参数与版本不重复塞进 Prompt。
    def model_view(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "capability_id": self.capability_id,
            "source_ref": self.source_ref,
            "title": self.title,
        }


# 将不受信任的标题/摘要压成有界单行；它不参与候选身份或权限判断。
def _preview(value: object, limit: int = 110) -> str:
    return " ".join(str(value or "").split())[:limit]


# 根据权威收据的身份与固定参数生成确定候选；跨观察位置编号不会碰撞到别的对象。
def _candidate(
    run_id: str,
    decision_id: str,
    capability_id: str,
    arguments: dict[str, Any],
    source_ref: str,
    title: str,
) -> ActionCandidate:
    identity = digest_json(
        {
            "protocol": "action-frontier-v1",
            "run_id": run_id,
            "source_decision_id": decision_id,
            "capability_id": capability_id,
            "arguments": arguments,
            "source_ref": source_ref,
        }
    )
    return ActionCandidate(
        "af_" + identity[:24],
        capability_id,
        arguments,
        decision_id,
        source_ref,
        _preview(title),
    )


# 纯函数从最近六步已结算检索构造最多八个不同目标；结果数据不得伪装为 Tool Receipt。
def build_action_frontier(
    run_id: str, activities: list[dict[str, Any]] | tuple[dict[str, Any], ...]
) -> tuple[ActionCandidate, ...]:
    if not isinstance(run_id, str) or not run_id:
        return ()
    used_ids = {
        args["candidate_id"]
        for item in activities
        if item.get("state") == "DONE" and isinstance(item.get("decision"), dict)
        for args in [item["decision"].get("arguments")]
        if isinstance(args, dict) and isinstance(args.get("candidate_id"), str)
        and isinstance(item.get("result"), dict) and not item["result"].get("failure")
    }
    candidates: list[ActionCandidate] = []
    seen_targets: set[tuple[str, str]] = set()
    # 最新观察优先；绝不因遍历历史而把失效检索结果当成当前权限。
    for item in reversed(activities[-6:]):
        if item.get("state") != "DONE" or not isinstance(item.get("result"), dict):
            continue
        decision, result = item.get("decision") or {}, item["result"]
        if not isinstance(decision, dict) or result.get("failure") or result.get("error"):
            continue
        source_kind = decision.get("capability_id")
        source_id = item.get("decision_id")
        if (
            source_kind not in _SUPPORTED_SOURCES
            or result.get("capability_id") != source_kind
            or not isinstance(source_id, str)
            or not source_id
        ):
            continue
        rows = result.get("sources") if source_kind == "knowledge.search" else result.get("memories")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if source_kind == "knowledge.search":
                target = row.get("document_id")
                version = row.get("digest")
                if (
                    not isinstance(target, str) or not 0 < len(target) <= 200
                    or not isinstance(version, str) or len(version) != 64
                    or any(c not in "0123456789abcdef" for c in version)
                ):
                    continue
                capability = "knowledge.resolve"
                arguments = {"document_id": target, "resolution": "L2", "expected_digest": version}
                source_ref = f"doc:{target}@{version}"
                title = f"{row.get('title') or target} · {row.get('content') or ''}"
            else:
                target = row.get("memory_id")
                version = row.get("revision")
                if (
                    not isinstance(target, str) or not 0 < len(target) <= 200
                    or type(version) is not int or version < 1 or row.get("is_stale") is not False
                ):
                    continue
                capability = "memory.resolve"
                arguments = {"memory_id": target, "resolution": "L2", "expected_revision": version}
                source_ref = f"memory:{target}@{version}"
                title = row.get("text") or target
            # 同一个目标只保留最近一次的版本视图；身份也包含原 Observation，禁止跨 Run 重绑。
            target_key = (capability, target)
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            candidate = _candidate(run_id, source_id, capability, arguments, source_ref, title)
            if candidate.candidate_id in used_ids:
                continue
            candidates.append(candidate)
            if len(candidates) >= MAX_ACTION_CANDIDATES:
                return tuple(candidates)
    return tuple(candidates)


# 模型仅能选择本次精确候选 ID；错误/跨工具/额外自由参数都在 Ticket 前拒绝。
def select_action_candidate(
    candidates: tuple[ActionCandidate, ...],
    capability_id: str,
    arguments: object,
) -> ActionCandidate:
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"candidate_id"}
        or not isinstance(arguments["candidate_id"], str)
    ):
        raise ValueError("candidate choice must contain only candidate_id")
    for candidate in candidates:
        if candidate.candidate_id == arguments["candidate_id"] and candidate.capability_id == capability_id:
            return candidate
    raise ValueError("action candidate is absent, stale or belongs to another capability")
