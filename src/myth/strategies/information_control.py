"""实时信息获取的纯准入策略。
把现有知识/项目读取工具解释为 SEEK 或 EXPAND，用已持久化 activity 重建本轮消费状态；
本模块不执行 I/O、不调用模型、不持有新的业务状态，也不把离线 Information Gain 冒充实时真值。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..domain import canonical_json


# InformationControlAction：信息环的稳定动作词汇；KEEP 由“停止继续取信息并推进任务”表达，不产生工具调用。
class InformationControlAction(StrEnum):
    # KEEP：当前信息足够，继续推理/执行/回答；无需额外信息工具。
    KEEP = "KEEP"
    # SEEK：寻找新的候选来源或导航范围。
    SEEK = "SEEK"
    # EXPAND：展开已知来源的更多细节/证据。
    EXPAND = "EXPAND"


# 一次实时信息准入结果；它是纯策略决定，不是 Tool Ticket、Receipt 或质量证明。
@dataclass(frozen=True)
class InformationControlDecision:
    # action：SEEK/EXPAND；KEEP 不需要进入 execute 路径。
    action: InformationControlAction
    # admitted：是否允许本次信息工具进入正常 Runtime Ticket 流程。
    admitted: bool
    # capability：模型提出的原工具身份；Controller 不发明另一套 Tool。
    capability: str
    # signature：规范化请求身份；用于拒绝同一 Run 内无进展的精确重复。
    signature: str
    # target_key：同一检索问题/文档/项目文件的稳定局部身份；只用于本轮限额。
    target_key: str
    # reason：可解释准入/拒绝原因；不是语义质量或 Information Gain 真值。
    reason: str
    # ordinal：若准入，本次将成为第几个实时信息动作；拒绝时表示下一机会序号。
    ordinal: int
    # total_limit：本轮实时信息动作硬上限；始终至少给最终非信息步骤留一个机会。
    total_limit: int
    # seek_count：本次之前已结算 SEEK 数量。
    seek_count: int
    # seek_limit：本轮 SEEK 上限。
    seek_limit: int
    # expand_count：本次之前已结算 EXPAND 数量。
    expand_count: int
    # expand_limit：本轮 EXPAND 上限。
    expand_limit: int
    # target_count：同 target/action 已结算次数；防止单一来源吞掉整轮。
    target_count: int
    # target_limit：当前 action 在单 target 上的次数上限。
    target_limit: int

    # 输出可持久/展示的小型投影；不携带原始正文，避免控制元数据反向膨胀 Context。
    def serializable(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "admitted": self.admitted,
            "capability": self.capability,
            "signature": self.signature,
            "target_key": self.target_key,
            "reason": self.reason,
            "ordinal": self.ordinal,
            "total_limit": self.total_limit,
            "seek_count": self.seek_count,
            "seek_limit": self.seek_limit,
            "expand_count": self.expand_count,
            "expand_limit": self.expand_limit,
            "target_count": self.target_count,
            "target_limit": self.target_limit,
        }


# 基于已有 durable activities 的有界实时控制器；删除它会把重复检测/预算/进展规则重新散回多个读取工具。
class LiveInformationController:
    # strategy_id：组织策略身份；属于 Context/Agent Loop 间的可替换策略，不是新执行层。
    strategy_id = "information_control"

    # _ACTIONS：只控制会把新信息带回模型的既有工具；写入/测试/Sub-Agent 不归本策略。
    _ACTIONS = {
        "knowledge.search": InformationControlAction.SEEK,
        "memory.search": InformationControlAction.SEEK,
        "project.search": InformationControlAction.SEEK,
        "project.list": InformationControlAction.SEEK,
        "knowledge.resolve": InformationControlAction.EXPAND,
        "knowledge.read": InformationControlAction.EXPAND,
        "memory.timeline": InformationControlAction.EXPAND,
        "memory.resolve": InformationControlAction.EXPAND,
        "project.read": InformationControlAction.EXPAND,
    }

    # 判断能力是否属于实时信息环；None 表示保持原执行路径。
    def action_for(self, capability: str) -> InformationControlAction | None:
        return self._ACTIONS.get(str(capability or ""))

    # 按工具默认值规范化请求；同义省略参数形成相同 signature，分页 cursor/offset 保持身份差异。
    @staticmethod
    def _normalized(capability: str, args: dict[str, Any]) -> dict[str, Any]:
        value = dict(args or {})
        if capability in {"knowledge.search", "memory.search"}:
            return {
                "query": str(value.get("query") or "").strip().casefold(),
                "limit": value.get("limit", 5),
            }
        if capability == "memory.timeline":
            return {
                "memory_id": str(value.get("memory_id") or "").strip(),
                "radius": value.get("radius", 2),
            }
        if capability == "memory.resolve":
            return {
                "memory_id": str(value.get("memory_id") or "").strip(),
                "resolution": str(value.get("resolution") or "L2").upper(),
            }
        if capability == "project.search":
            return {
                "query": str(value.get("query") or "").strip().casefold(),
                "path": str(value.get("path") or ".").strip(),
                "limit": value.get("limit", 12),
                "cursor": value.get("cursor", 0),
                "max_files": value.get("max_files", 500),
            }
        if capability == "project.list":
            return {"path": str(value.get("path") or ".").strip()}
        if capability == "knowledge.resolve":
            resolution = str(value.get("resolution") or "L2").upper()
            return {
                "document_id": str(value.get("document_id") or "").strip(),
                "resolution": resolution,
                "cursor": value.get("cursor", 0),
                "limit": value.get("limit", 6000 if resolution == "L2" else 12),
            }
        if capability == "knowledge.read":
            return {
                "document_id": str(value.get("document_id") or "").strip(),
                "offset": value.get("offset", 0),
                "max_chars": value.get("max_chars", 6000),
            }
        if capability == "project.read":
            return {
                "path": str(value.get("path") or "").strip(),
                "offset": value.get("offset", 0),
                "max_chars": value.get("max_chars", value.get("limit", 6000)),
            }
        return value

    # 生成单 target 身份；分页参数不进入 target，使同一问题/来源共享局部预算。
    @staticmethod
    def _target_key(capability: str, normalized: dict[str, Any]) -> str:
        if capability in {"knowledge.search", "memory.search"}:
            return canonical_json({"kind": capability, "query": normalized["query"]})
        if capability in {"memory.timeline", "memory.resolve"}:
            return canonical_json(
                {"kind": "memory", "memory_id": normalized["memory_id"]}
            )
        if capability == "project.search":
            return canonical_json(
                {
                    "kind": capability,
                    "query": normalized["query"],
                    "path": normalized["path"],
                }
            )
        if capability == "project.list":
            return canonical_json({"kind": capability, "path": normalized["path"]})
        if capability in {"knowledge.resolve", "knowledge.read"}:
            return canonical_json(
                {"kind": "knowledge", "document_id": normalized["document_id"]}
            )
        if capability == "project.read":
            return canonical_json({"kind": "project.read", "path": normalized["path"]})
        return canonical_json({"kind": capability})

    # 从已结算 activity 读取此前控制记录；恢复后重建同样状态，不依赖进程内计数器。
    @staticmethod
    def _records(turn: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        records = []
        for activity in turn.get("activities", ()):
            result = activity.get("result") or {}
            control = result.get("information_control")
            if isinstance(control, dict) and control.get("admitted"):
                records.append((control, result))
        return records

    # 根据 Run 总步数派生信息预算；最多八次，并始终为最终回答/非信息动作留下至少一个 Step。
    @staticmethod
    def _limits(turn: dict[str, Any]) -> tuple[int, int, int]:
        max_steps = max(2, int(turn.get("max_steps") or 2))
        total = max(1, min(8, max_steps - 1))
        return total, min(4, total), min(6, total)

    # 对当前信息工具做纯准入；精确重复、无进展分页、全局/局部预算超限均在 Tool Ticket 前拒绝。
    def admit(
        self, turn: dict[str, Any], capability: str, args: dict[str, Any] | None
    ) -> InformationControlDecision | None:
        action = self.action_for(capability)
        if action is None:
            return None

        normalized = self._normalized(capability, dict(args or {}))
        signature = canonical_json({"capability": capability, "arguments": normalized})
        target_key = self._target_key(capability, normalized)
        records = self._records(turn)
        total_limit, seek_limit, expand_limit = self._limits(turn)
        seek_count = sum(1 for row, _ in records if row.get("action") == "SEEK")
        expand_count = sum(1 for row, _ in records if row.get("action") == "EXPAND")
        target_count = sum(
            1
            for row, _ in records
            if row.get("action") == action.value
            and row.get("target_key") == target_key
        )
        target_limit = 3 if action is InformationControlAction.SEEK else 4

        # 把当前计数与限额冻结进同一返回合同；调用方只消费结果，不重复拼装控制元数据。
        def decision(admitted: bool, reason: str) -> InformationControlDecision:
            return InformationControlDecision(
                action=action,
                admitted=admitted,
                capability=capability,
                signature=signature,
                target_key=target_key,
                reason=reason,
                ordinal=len(records) + 1,
                total_limit=total_limit,
                seek_count=seek_count,
                seek_limit=seek_limit,
                expand_count=expand_count,
                expand_limit=expand_limit,
                target_count=target_count,
                target_limit=target_limit,
            )

        if any(row.get("signature") == signature for row, _ in records):
            return decision(
                False,
                "exact information request already settled; use existing observation or make a progressing request",
            )
        if len(records) >= total_limit:
            return decision(
                False,
                "live information budget exhausted; KEEP current information and continue the task",
            )
        if action is InformationControlAction.SEEK and seek_count >= seek_limit:
            return decision(
                False,
                "SEEK budget exhausted; use admitted sources or continue the task",
            )
        if action is InformationControlAction.EXPAND and expand_count >= expand_limit:
            return decision(
                False,
                "EXPAND budget exhausted; use current evidence or continue the task",
            )
        if target_count >= target_limit:
            return decision(
                False,
                "single-source information budget exhausted; avoid tunneling on one source",
            )

        # 同一分页视图已经明确耗尽时，禁止用不同 cursor 继续制造“新”请求；改变 resolution 仍是另一视图。
        pagination_group = self._pagination_group(capability, normalized)
        if pagination_group is not None:
            for row, result in reversed(records):
                if row.get("pagination_group") != pagination_group:
                    continue
                if result.get("has_more") is False:
                    return decision(
                        False,
                        "this information view is already exhausted; KEEP or choose a different source/resolution",
                    )
                next_position = result.get("next_cursor", result.get("next_offset"))
                current_position = normalized.get("cursor", normalized.get("offset", 0))
                if (
                    type(next_position) is int
                    and type(current_position) is int
                    and current_position < next_position
                ):
                    return decision(
                        False,
                        f"pagination must progress to at least {next_position}",
                    )
                break

        return decision(
            True,
            "novel progressing information request is within the bounded live-control budget",
        )

    # 同一分页视图身份包含 query/source + resolution，但不包含 cursor；用于判断 exhausted/progress。
    @staticmethod
    def _pagination_group(
        capability: str, normalized: dict[str, Any]
    ) -> str | None:
        if capability == "project.search":
            return canonical_json(
                {
                    "kind": capability,
                    "query": normalized["query"],
                    "path": normalized["path"],
                }
            )
        if capability == "knowledge.resolve":
            return canonical_json(
                {
                    "kind": capability,
                    "document_id": normalized["document_id"],
                    "resolution": normalized["resolution"],
                }
            )
        if capability == "knowledge.read":
            return canonical_json(
                {"kind": capability, "document_id": normalized["document_id"]}
            )
        if capability == "project.read":
            return canonical_json(
                {"kind": capability, "path": normalized["path"]}
            )
        return None

    # 把准入决定补上分页组与实际返回字节，供下一步和 Runtime Observatory 使用。
    def record_result(
        self,
        decision: InformationControlDecision,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        projection = decision.serializable()
        projection["pagination_group"] = self._pagination_group(
            decision.capability,
            self._normalized(decision.capability, self._arguments_from_result(decision, result)),
        )
        projection["result_bytes"] = len(canonical_json(result).encode("utf-8"))
        return projection

    # result 不可靠地包含原参数；分页组已经能由 decision.target/signature 表达时从 signature 反解析原 arguments。
    @staticmethod
    def _arguments_from_result(
        decision: InformationControlDecision, result: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            import json

            payload = json.loads(decision.signature)
            args = payload.get("arguments")
            return args if isinstance(args, dict) else {}
        except (ValueError, TypeError):
            return {}

    # 生成只读运行摘要；拒绝记录从 activity error 前缀统计，既不修改 Turn 也不制造新的执行事实。
    def summary(self, turn: dict[str, Any]) -> dict[str, Any]:
        records = self._records(turn)
        total_limit, seek_limit, expand_limit = self._limits(turn)
        denied = 0
        for activity in turn.get("activities", ()):
            result = activity.get("result") or {}
            if str(result.get("error") or "").startswith("information control denied:"):
                denied += 1
        seek_count = sum(1 for row, _ in records if row.get("action") == "SEEK")
        expand_count = sum(1 for row, _ in records if row.get("action") == "EXPAND")
        last = records[-1][0] if records else None
        return {
            "policy": "bounded-live-v1",
            "actions": len(records),
            "total_limit": total_limit,
            "seek": seek_count,
            "seek_limit": seek_limit,
            "expand": expand_count,
            "expand_limit": expand_limit,
            "denied": denied,
            "last_action": last.get("action") if last else "KEEP",
            "last_capability": last.get("capability") if last else None,
            "result_bytes": sum(
                max(0, int(row.get("result_bytes") or 0)) for row, _ in records
            ),
        }
