"""事件事实的纯轨迹投影。
只汇总已记录事件；不拥有 Run 状态，不根据动画或文本猜测 Ticket、预算或验收事实。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 已发生事件的纯投影合同；sequence 表示本 Run 的持久事件顺序。
@dataclass(frozen=True)
class TraceEvent:
    # sequence：本 Run 的持久事件序号，单调分配。
    sequence: int
    # layer：轨迹分类字段；沿用数据合同，不把分类变成强制执行层。
    layer: str
    # kind：当前合同的对象/记忆用途分类；需与所属枚举解释。
    kind: str
    # payload：事件/命令的数据负载；不得包含认证秘钥。
    payload: dict[str, Any]


# 根据已记录事件统计轨迹；未知事件数量是观测，不改变执行状态。
class TraceProjection:
    # 从真实已给事件统计类别、unknown 和最后序号；投影不修正业务状态。
    def summarize(self, events: list[TraceEvent]) -> dict[str, Any]:
        by_layer: dict[str, int] = {}
        unknown = 0
        for event in events:
            by_layer[event.layer] = by_layer.get(event.layer, 0) + 1
            if "unknown" in event.kind.lower():
                unknown += 1
        return {
            "events": len(events),
            "by_layer": dict(sorted(by_layer.items())),
            "unknown_events": unknown,
            "last_sequence": max((event.sequence for event in events), default=0),
        }


    # 从已有模型调用、决定与工具操作投影 Execution Graph；图只是观测视图，不写入新的 Run 真相。
    def execution_graph(
        self,
        *,
        run_id: str,
        status: str,
        model_state: dict[str, Any],
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        invocations = list(model_state.get("model_invocations") or [])
        decisions = list(model_state.get("decisions") or [])
        decision_by_attempt = {
            item.get("model_attempt_id"): item
            for item in decisions
            if item.get("model_attempt_id")
        }
        operation_by_decision = {
            item.get("decision_id"): item
            for item in operations
            if item.get("decision_id")
        }
        invocation_by_key = {
            str(item.get("request_key")): item
            for item in invocations
            if item.get("request_key")
        }

        nodes: list[dict[str, Any]] = [
            {
                "id": f"run:{run_id}",
                "kind": "run",
                "label": "Run",
                "detail": run_id,
                "state": status,
                "depth": 0,
            }
        ]
        edges: list[dict[str, str]] = []
        mapped_attempts: set[str] = set()
        cursor = f"run:{run_id}"
        conversation_prefix = f"conversation:{run_id}:"
        subagent_prefix = f"subagent:{run_id}:"

        parent_calls: list[tuple[int, dict[str, Any]]] = []
        for ordinal, invocation in enumerate(invocations):
            request_key = str(invocation.get("request_key") or "")
            if request_key.startswith(conversation_prefix):
                raw_step = request_key[len(conversation_prefix) :]
                try:
                    step = int(raw_step)
                except ValueError:
                    step = ordinal + 1
                parent_calls.append((step, invocation))
        parent_calls.sort(key=lambda item: item[0])

        for step, invocation in parent_calls:
            attempt_id = str(invocation.get("model_attempt_id") or "")
            if attempt_id:
                mapped_attempts.add(attempt_id)
            decision = decision_by_attempt.get(invocation.get("model_attempt_id")) or {}
            payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
            decision_type = str(
                decision.get("decision_type")
                or payload.get("decision_type")
                or "model"
            )
            capability = str(payload.get("capability_id") or "")
            detail = capability if decision_type == "tool_call" and capability else decision_type
            parent_id = f"model:{attempt_id or step}"
            nodes.append(
                {
                    "id": parent_id,
                    "kind": "model",
                    "label": f"Parent model · step {step}",
                    "detail": detail,
                    "state": invocation.get("state") or invocation.get("outcome") or "UNKNOWN",
                    "depth": 0,
                    "request_key": invocation.get("request_key"),
                    "attempt_id": invocation.get("model_attempt_id"),
                    "decision_id": decision.get("decision_id"),
                }
            )
            edges.append({"source": cursor, "target": parent_id, "kind": "next"})
            cursor = parent_id

            decision_id = decision.get("decision_id")
            operation = operation_by_decision.get(decision_id)
            if not operation:
                continue

            tool_id = f"tool:{decision_id}"
            nodes.append(
                {
                    "id": tool_id,
                    "kind": "tool",
                    "label": str(operation.get("capability") or capability or "Tool"),
                    "detail": str(operation.get("ticket_id") or decision_id or ""),
                    "state": operation.get("state") or "UNKNOWN",
                    "depth": 1,
                    "decision_id": decision_id,
                    "ticket_id": operation.get("ticket_id"),
                }
            )
            edges.append({"source": parent_id, "target": tool_id, "kind": "tool"})
            cursor = tool_id

            result = operation.get("result") if isinstance(operation.get("result"), dict) else {}
            child = result.get("subagent") if isinstance(result.get("subagent"), dict) else {}
            child_request_key = str(child.get("request_key") or "")
            if not child_request_key and capability == "agent.delegate" and decision_id:
                prefix = f"{subagent_prefix}{decision_id}:"
                child_request_key = next(
                    (key for key in invocation_by_key if key.startswith(prefix)),
                    "",
                )
            child_invocation = invocation_by_key.get(child_request_key)
            if not child_invocation:
                continue

            child_attempt_id = str(child_invocation.get("model_attempt_id") or "")
            if child_attempt_id:
                mapped_attempts.add(child_attempt_id)
            role_id = str(child.get("role_id") or "")
            if not role_id and child_request_key.startswith(subagent_prefix):
                remainder = child_request_key[len(subagent_prefix) :]
                if ":" in remainder:
                    _, role_id = remainder.rsplit(":", 1)
            child_id = f"subagent:{child_attempt_id or decision_id}"
            nodes.append(
                {
                    "id": child_id,
                    "kind": "subagent",
                    "label": f"Sub-Agent · {role_id or 'worker'}",
                    "detail": "isolated delegated model call",
                    "state": child_invocation.get("state")
                    or child_invocation.get("outcome")
                    or "UNKNOWN",
                    "depth": 2,
                    "request_key": child_request_key,
                    "attempt_id": child_invocation.get("model_attempt_id"),
                    "parent_decision_id": decision_id,
                    "role_id": role_id or None,
                }
            )
            edges.append({"source": tool_id, "target": child_id, "kind": "delegate"})
            cursor = child_id

        terminal_id = f"state:{run_id}"
        nodes.append(
            {
                "id": terminal_id,
                "kind": "state",
                "label": "Run state",
                "detail": "durable status projection",
                "state": status,
                "depth": 0,
            }
        )
        edges.append({"source": cursor, "target": terminal_id, "kind": "state"})

        total_attempts = {
            str(item.get("model_attempt_id"))
            for item in invocations
            if item.get("model_attempt_id")
        }
        unmapped = total_attempts - mapped_attempts
        return {
            "version": "execution-graph-v1",
            "experimental": True,
            "nodes": nodes,
            "edges": edges,
            "coverage": {
                "model_calls": len(total_attempts),
                "mapped_model_calls": len(mapped_attempts),
                "unmapped_model_calls": len(unmapped),
            },
        }
