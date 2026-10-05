"""事件事实的纯轨迹投影。
只汇总已记录事件；不拥有 Run 状态，不根据动画或文本猜测 Ticket、预算或验收事实。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from .model_pool import estimate_cost


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
        main_pricing: dict | None = None,
        main_model: str | None = None,
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
            if result.get("fallback_to_parent"):
                nodes[-1].update({"detail": "主模型接手：" + str(result.get("summary") or "模型池不可用"),
                                  "routing": result.get("routing"), "fallback_to_parent": True})
            branch_operations = ([operation_by_decision[c["delegation_id"]]
                                  for c in (operation.get("intent") or {}).get("parallel", [])]
                                 if "parallel" in (operation.get("intent") or {}) else [operation])
            tails = []
            for branch in branch_operations:
                branch_id = branch["decision_id"]
                branch_tool = tool_id
                if branch is not operation:
                    branch_tool = f"tool:{branch_id}"
                    nodes.append({"id": branch_tool, "kind": "tool", "label": "agent.delegate",
                        "detail": "并行子任务", "state": branch["state"], "depth": 2,
                        "decision_id": branch_id, "ticket_id": branch.get("ticket_id")})
                    edges.append({"source": tool_id, "target": branch_tool, "kind": "fork"})
                branch_result = branch.get("result") or {}
                child = branch_result.get("subagent") or {}
                contract = (branch.get("intent") or {}).get("delegate") or {}
                child_request_key = child.get("request_key") or contract.get("request_key") or (
                    f"{subagent_prefix}{branch_id}:" if branch.get("capability") == "agent.delegate" else "")
                branch_cursor = branch_tool
                child_calls = [x for x in invocations if child_request_key and
                    (x.get("request_key") == child_request_key or str(x.get("request_key") or "").startswith(child_request_key + ":"))]
                for ordinal, child_invocation in enumerate(child_calls, 1):
                    child_attempt_id = str(child_invocation.get("model_attempt_id") or "")
                    if child_attempt_id:
                        mapped_attempts.add(child_attempt_id)
                    child_id = f"subagent:{child_attempt_id or branch_id}"
                    nodes.append({"id": child_id, "kind": "subagent", "label": f"子模型 · 调用 {ordinal}",
                        "detail": "隔离子流程", "state": child_invocation.get("state") or "UNKNOWN", "depth": 3 if branch is not operation else 2,
                        "request_key": child_invocation.get("request_key"), "attempt_id": child_attempt_id,
                        "parent_decision_id": branch_id, "role_id": child.get("role_id") or "isolated_worker",
                        "batch_id": contract.get("batch_id"), "ordinal": contract.get("ordinal")})
                    edges.append({"source": branch_cursor, "target": child_id, "kind": "delegate" if ordinal == 1 else "child_next"})
                    branch_cursor = child_id
                    child_decision = decision_by_attempt.get(child_attempt_id) or {}
                    child_op = operation_by_decision.get(child_decision.get("decision_id"))
                    if child_op:
                        input_id = f"tool:{child_op['decision_id']}"
                        nodes.append({"id": input_id, "kind": "tool", "label": child_op["capability"], "detail": "子任务输入回读",
                            "state": child_op["state"], "depth": 3, "decision_id": child_op["decision_id"], "ticket_id": child_op.get("ticket_id")})
                        edges.append({"source": child_id, "target": input_id, "kind": "tool"})
                        branch_cursor = input_id
                for dependency in contract.get("depends_on", []):
                    edges.append({"source": f"tool:{dependency}", "target": branch_tool, "kind": "dependency"})
                if contract.get("replaces"):
                    edges.append({"source": f"tool:{contract['replaces']}", "target": branch_tool, "kind": "replacement"})
                tails.append(branch_cursor)
            if "parallel" in (operation.get("intent") or {}):
                join_id = f"join:{decision_id}"
                nodes.append({"id": join_id, "kind": "tool", "label": "并行汇合", "depth": 1,
                    "detail": "按固定任务顺序交接", "state": operation["state"],
                    "parallel": result.get("parallel")})
                for tail in tails or [tool_id]:
                    edges.append({"source": tail, "target": join_id, "kind": "join"})
                cursor = join_id
            elif tails:
                cursor = tails[-1]

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

        # 节点只展示收据与父评分；每个模型 Attempt 单独计一次，父工具收据不重复加费用。
        child_contracts = {(op.get("intent") or {}).get("delegate", {}).get("request_key"):
                           (op.get("intent") or {}).get("delegate", {}) for op in operations}
        reviews = {(op.get("result") or {}).get("review", {}).get("delegation_id"):
                   (op.get("result") or {}).get("review") for op in operations if (op.get("result") or {}).get("review")}
        invocation_by_id = {i.get("model_attempt_id"): i for i in invocations}
        # 子 key 包含步骤后缀；精确前缀分隔避免把其他委派算到当前合同。
        contracts_by_attempt = {i.get("model_attempt_id"): next((c for key, c in child_contracts.items()
            if key and (i.get("request_key") == key or str(i.get("request_key") or "").startswith(key + ":"))), {}) for i in invocations}
        costs = []
        review_buckets = {"reviewed": {}, "pending": {}, "disputed": {}}
        unknown_by_review = {"reviewed": 0, "pending": 0, "disputed": 0}
        for invocation in invocations:
            contract = contracts_by_attempt[invocation.get("model_attempt_id")]
            profile = (contract.get("routing") or {}).get("profile") or {}
            rates = profile.get("pricing") if contract else (main_pricing if main_model is None or invocation.get("model_id") == main_model else None)
            cost = estimate_cost(invocation.get("usage") or {}, rates)
            costs.append(cost)
            verdict = (reviews.get(contract.get("delegation_id")) or {}).get("metadata_verdict")
            bucket = "reviewed" if not contract or verdict == "accepted" else "disputed" if verdict == "disputed" else "pending"
            if cost["amount"] is None:
                unknown_by_review[bucket] += 1
            else:
                totals = review_buckets[bucket]
                totals[cost["currency"]] = round(totals.get(cost["currency"], 0) + cost["amount"], 9)
        for node in nodes:
            invocation = invocation_by_id.get(node.get("attempt_id"))
            if not invocation:
                continue
            contract = contracts_by_attempt[invocation.get("model_attempt_id")]
            profile = (contract.get("routing") or {}).get("profile") or {}
            node.update({"provider": invocation.get("provider_id"), "model": invocation.get("model_id"),
                         "usage": invocation.get("usage") or {}, "routing": contract.get("routing"),
                         "review": reviews.get(contract.get("delegation_id")),
                         "cost": estimate_cost(invocation.get("usage") or {}, profile.get("pricing") if contract else (main_pricing if main_model is None or invocation.get("model_id") == main_model else None))})
            if node["review"]:
                reviewer = next((op for op in operations if (op.get("result") or {}).get("review") == node["review"]), None)
                if reviewer:
                    edges.append({"source": node["id"], "target": f"tool:{reviewer['decision_id']}", "kind": "review"})
        totals = {}
        for cost in costs:
            if cost["amount"] is not None:
                totals[cost["currency"]] = round(totals.get(cost["currency"], 0) + cost["amount"], 9)

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
            "cost_summary": {"estimated_by_currency": totals, "unknown_calls": sum(c["amount"] is None for c in costs),
                             "model_calls": len(invocations), "basis": "configured_list_price",
                             "reviewed_by_currency": review_buckets["reviewed"], "pending_by_currency": review_buckets["pending"],
                             "disputed_by_currency": review_buckets["disputed"], "unknown_by_review": unknown_by_review},
            "coverage": {
                "model_calls": len(total_attempts),
                "mapped_model_calls": len(mapped_attempts),
                "unmapped_model_calls": len(unmapped),
            },
        }
