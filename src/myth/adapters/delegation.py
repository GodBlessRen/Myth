"""委派、交接回读和主模型评审的外圈协调入口。

父工具先准入；子流程用共同引擎，完整内容/元数据留不可变对象，默认观察有界。
主模型可拒收内容并采信花销，或争议元数据；已发生调用永远保留在共同账本。
"""

from __future__ import annotations

import json

from ..domain import ExecutionDeferred, RecoveryRequired, canonical_json, digest_json, sha256_bytes
from ..models import ProviderUnavailable, StepDecision
from ..platform.model_pool import clean_pool, route, profile_key, estimate_cost
from ..platform.handoff import public_metadata
from .subagent_runtime import run_subagent


class DelegationCoordinator:
    """固定交接信封，协调子游标与父收据；评分不能修改调用事实或隐式发布新权限。"""

    def __init__(self, execution):
        """连接实际工具执行器；Provider 仍由装配根的工厂解析。"""
        # execution：父工具/模型收据的执行协作者。
        self.execution = execution
        # repository：工作区持久状态所有者。
        self.repository = execution.repository
        # runtime：共同对象、预算与事件账本。
        self.runtime = execution.runtime

    def _target(self, turn, delegation_id):
        """核对同 Run 且已结算的真实委派，跨 Run、猜测 ID 与未决效果都拒绝。"""
        if not isinstance(delegation_id, str) or not 1 <= len(delegation_id) <= 200:
            raise ValueError("invalid delegation_id")
        op = self.repository.operation(delegation_id)
        if not op or op["run_id"] != turn["run_id"] or op["capability"] != "agent.delegate" or op["state"] != "RESOLVED":
            raise ValueError("只能引用本轮已结算的子任务")
        if not (op.get("result") or {}).get("handoff"):
            raise ValueError("模型池回退未产生子结果，无需评分或回读")
        return op

    def delegate(self, turn, decision_id, args, provider, *, force_factory=False):
        """固定输入/模型/依赖/顺序后派发；恢复使用原合同，不重新路由已经在途的任务。"""
        if provider is None and not force_factory:
            raise ValueError("agent.delegate requires the turn provider")
        old = self.repository.operation(decision_id)
        if old:
            if old["state"] == "RESOLVED":
                return old["result"]
            contract, op = old["intent"]["delegate"], old
        else:
            contract = self.prepare(turn, decision_id, args)
            if contract.get("fallback_to_parent"):
                return contract
            # 父 Ticket 先于子上下文编译/模型派发；后续子模型及输入读取仍使用父预算。
            op = self.repository.start_operation(turn["run_id"], decision_id, "agent.delegate", {
                "write_bytes": 0, "requires_receipt": True, "delegate": contract})
        profile = contract["routing"]["profile"]
        child_provider = provider
        if force_factory or profile["provider"] != turn["settings"]["provider"] or (profile["provider"] == "ollama" and profile["ollama_url"] != turn["settings"]["ollama_url"]):
            try:
                child_provider = self.execution.provider_factory(profile)
            except (ValueError, OSError, RuntimeError):
                # 工厂尚未调用模型；保存明确的零派发故障，主模型仍须处理替代工作。
                from .subagent_runtime import SubagentRepository
                repository = SubagentRepository(self.repository, contract)
                repository.block(contract["delegation_id"], "FAILED", "子模型连接配置不可用，未派发请求")
                return self.result(contract, repository.state())
        state = run_subagent(self.execution, contract, child_provider)
        if state["status"] == "INTERRUPTED":
            raise ProviderUnavailable()
        if state["status"] == "UNKNOWN":
            raise RecoveryRequired("delegated model outcome is unresolved")
        if state["status"] not in {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "CANCELLED"}:
            raise ExecutionDeferred("child execution is paused or needs continuation")
        return self.result(contract, state)

    def prepare(self, turn, decision_id, args):
        """纯准备固定输入、路由与依赖；返回合同或明确回退，不创建 Ticket、不访问 Provider。"""
        spec = self.execution.subagents.get("isolated_worker")
        task, context, expected = args.get("task"), args.get("context", ""), args.get("expected_output", "")
        if not isinstance(task, str) or not task.strip() or len(task) > spec.max_task_chars:
            raise ValueError("agent.delegate task must be non-empty and within the role limit")
        if not isinstance(context, str) or len(context) > spec.max_context_chars:
            raise ValueError("agent.delegate context exceeds the role limit")
        if not isinstance(expected, str) or len(expected) > spec.max_expected_output_chars:
            raise ValueError("agent.delegate expected_output exceeds the role limit")
        refs = args.get("source_refs", [])
        if not isinstance(refs, list) or any(not isinstance(x, str) or len(x) > 500 for x in refs) or len(refs) > spec.max_source_refs:
            raise ValueError("invalid delegated source_refs")
        refs = list(dict.fromkeys(x.strip() for x in refs if x.strip()))
        if any(x not in self.execution._available_subagent_source_refs(turn) for x in refs):
            raise ValueError("agent.delegate source_refs must come from admitted parent observations")
        dependencies, replaces = args.get("depends_on", []), args.get("replaces")
        if not isinstance(dependencies, list) or len(dependencies) > 3 or any(not isinstance(x, str) for x in dependencies):
            raise ValueError("invalid delegation dependencies")
        reviews = {((x.get("result") or {}).get("review") or {}).get("delegation_id"):
                   (x.get("result") or {}).get("review") for x in self.repository.operations(turn["run_id"])}
        for target in dependencies:
            self._target(turn, target)
            if not (reviews.get(target) or {}).get("accepted"):
                raise ValueError("依赖结果须先由主模型采用，不能依赖未评分或已拒收结果")
        if replaces:
            self._target(turn, replaces)
            if not reviews.get(replaces) or reviews[replaces]["accepted"]:
                raise ValueError("重新派发只能取代已拒收的本轮子任务")
        settings = turn["settings"]
        if settings["max_steps"] - turn["current_step"] < 2:
            return {"capability_id": "agent.delegate", "fallback_to_parent": True, "summary": "剩余步骤不足以评分与汇总，请主模型自行完成。"}
        pool = clean_pool(settings.get("model_pool"))
        for candidate in pool["children"]:
            candidate["effective_output_tokens"] = min(candidate["max_output_tokens"], settings["max_output_tokens"],
                max(64, self.execution.subagents.child_budget(spec.role_id, {"output_tokens": settings["max_output_tokens"]})["output_tokens"]))
        unavailable = [((x.get("result") or {}).get("routing") or {}).get("profile", {}).get("id")
                       for x in self.repository.operations(turn["run_id"]) if (x.get("result") or {}).get("fallback_reason") == "provider_failure"]
        routing = route(pool, args.get("task_type", "general"), args.get("difficulty", "medium"),
            self.repository.model_feedback(), unavailable, args.get("profile_id"))
        profile = routing["profile"]
        if profile is None:
            return {"capability_id": "agent.delegate", "routing": routing, "fallback_to_parent": True,
                    "summary": "没有满足要求的可用子模型，请主模型自行完成。"}
        context_digest = sha256_bytes(context.encode())
        contract = {"protocol_version": "handoff-v2", "run_id": turn["run_id"], "delegation_id": decision_id,
            "sequence": turn["current_step"], "depends_on": dependencies, "replaces": replaces,
            "task": task.strip(), "context": context, "expected_output": expected,
            "task_digest": digest_json({"task": task.strip(), "expected_output": expected}),
            "context_digest": context_digest, "input_source_ref": f"delegation-input:{decision_id}@{context_digest}",
            "source_refs": refs, "role_id": spec.role_id, "max_steps": profile["max_steps"],
            "output_token_limit": profile["effective_output_tokens"], "routing": routing,
            "request_key": f"subagent:{turn['run_id']}:{decision_id}:{spec.role_id}"}
        return contract

    def telemetry(self, contract):
        """附加全部子 Attempt 的公开计量；零派发重试、失败及拒收调用不会丢失或重复计价。"""
        calls = [x for x in self.repository.decisions.status(contract["run_id"])["model_invocations"]
                 if x.get("request_key") == contract["request_key"] or str(x.get("request_key") or "").startswith(contract["request_key"] + ":")]
        reports = []
        for call in calls:
            raw = json.loads(self.runtime.objects.get(call["response_ref"])) if call.get("response_ref") else {}
            reports.append({"attempt_id": call["model_attempt_id"], "request_key": call.get("request_key"),
                "state": call["state"], "outcome": call.get("outcome"), "provider": call["provider_id"], "model": call["model_id"],
                "response_id": call.get("response_id"), "response_ref": call.get("response_ref"),
                "usage": call.get("usage") or {}, "provider_metadata": public_metadata(raw),
                "cost": estimate_cost(call.get("usage") or {}, contract["routing"]["profile"].get("pricing"))})
        usage = {}
        for key in {k for r in reports for k in r["usage"]}:
            values = [r["usage"].get(key) for r in reports]
            if all(type(v) is int and v >= 0 for v in values):
                usage[key] = sum(values)
        if not calls:
            usage.update({"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "provider_wall_ms": 0})
        metadata = {"version": "provider-report-v1", "delegation_id": contract["delegation_id"], "calls": reports}
        report_ref = self.runtime.objects.put(canonical_json(metadata).encode())
        profile = contract["routing"]["profile"]
        return {"provider": profile["provider"], "model": profile["model"], "usage": usage,
            "provider_wall_ms": usage.get("provider_wall_ms"), "cost": estimate_cost(usage, profile.get("pricing")),
            "report_ref": report_ref, "report_digest": report_ref, "attempt_ids": [r["attempt_id"] for r in reports],
            "metadata_review": "pending", "source": "durable_provider_receipts"}

    def result(self, contract, state):
        """固定完整正文对象，向父默认返回有界摘要/身份/计量概况；核对模式同样使用此投影。"""
        worker = StepDecision(**state["steps"][-1]["decision"]) if state["status"] == "COMPLETED" else None
        content = worker.claim if worker else state.get("error") or "子任务未完成"
        content_ref = self.runtime.objects.put(content.encode())
        summary = worker.summary if worker and worker.summary else content[:1200]
        kind = "model_summary" if worker and worker.summary else "complete_text" if len(content) <= 1200 else "exact_excerpt"
        telemetry = self.telemetry(contract)
        return {"capability_id": "agent.delegate", "delegation_id": contract["delegation_id"],
            "routing": contract["routing"], "telemetry": telemetry, "review_required": True,
            "summary": summary, "summary_kind": kind, "coverage": worker.goal_coverage if worker else "",
            "evidence_refs": list(worker.evidence_refs) if worker else [],
            "remaining": list(worker.remaining) if worker else [content[:500]],
            "subagent": {"role_id": contract["role_id"], "request_key": contract["request_key"],
                "decision_id": state.get("final_decision_id"), "context_isolated": True, "write_access": False,
                "recursive_delegation": False, "max_steps": contract["max_steps"], "steps_used": state["current_step"],
                "output_token_limit": contract["output_token_limit"], "status": state["status"]},
            "handoff": {"version": "handoff-v2", "sequence": contract["sequence"], "depends_on": contract["depends_on"],
                "batch_id": contract.get("batch_id"), "ordinal": contract.get("ordinal"),
                "replaces": contract["replaces"], "task_digest": contract["task_digest"], "context_digest": contract["context_digest"],
                "content_ref": content_ref, "content_digest": content_ref, "content_chars": len(content),
                "summary_is_full_content": kind == "complete_text", "metadata_digest": telemetry["report_digest"],
                "read_capability": "agent.result"},
            "source_ref_sharing": {"shared_refs": contract["source_refs"], "accepted_refs": list(worker.evidence_refs) if worker else [], "history_inherited": False},
            **({"fallback_to_parent": True, "fallback_reason": "child_budget" if state["status"] == "BUDGET_EXHAUSTED"
                else "cancelled" if state["status"] == "CANCELLED" else "provider_failure"} if worker is None else {})}

    def read_result(self, turn, args):
        """分页回读固定原文、全部公开元数据或子流程检查点；摘要核对与范围核对先于返回。"""
        op = self._target(turn, args.get("delegation_id"))
        result = op["result"]
        field = args.get("field", "content")
        if field == "content":
            ref = result["handoff"]["content_ref"]
        elif field == "metadata":
            ref = result["telemetry"]["report_ref"]
        elif field == "trace":
            text = canonical_json(self.repository.delegation_state(op["decision_id"]))
            ref = self.runtime.objects.put(text.encode())
        else:
            raise ValueError("agent.result field must be content/metadata/trace")
        text = self.runtime.objects.get(ref).decode()
        if args.get("expected_digest") and args["expected_digest"] != ref:
            raise ValueError("交接对象版本已变，请使用当前信封中的摘要")
        offset, limit = args.get("offset", 0), args.get("max_chars", 3000)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 6000:
            raise ValueError("invalid handoff pagination")
        return {"delegation_id": op["decision_id"], "field": field, "content": text[offset:offset + limit],
            "source_digest": ref, "source_chars": len(text), "offset": offset, "has_more": offset + limit < len(text),
            "next_offset": offset + limit if offset + limit < len(text) else None,
            "source_ref": f"handoff:{op['decision_id']}:{field}@{ref}", "projection": "exact-recall"}

    def evaluate(self, turn, args):
        """内容评分与元数据采信分别绑定不可变摘要；分数不能修改 Usage 或掩盖已花费用。"""
        op = self._target(turn, args.get("delegation_id"))
        result = op["result"]
        scores = {k: args.get(k) for k in ("correctness", "completeness", "usefulness")}
        if any(type(x) is not int or not 0 <= x <= 100 for x in scores.values()):
            raise ValueError("评分必须为 0–100 整数")
        accepted, kind, note = args.get("accepted"), args.get("failure_kind", "none"), args.get("reason", "")
        if type(accepted) is not bool or kind not in {"none", "quality", "context", "infrastructure"}:
            raise ValueError("invalid review verdict")
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
            raise ValueError("评分须附有简短理由")
        if accepted and (kind != "none" or result.get("remaining") or result.get("fallback_to_parent")):
            raise ValueError("有未完成项或失败原因时不能评为通过")
        if not accepted and kind == "none":
            raise ValueError("未通过须区分质量、上下文或运行故障")
        verdict = args.get("metadata_verdict")
        if verdict not in {"accepted", "incomplete", "disputed"}:
            raise ValueError("invalid metadata verdict")
        tier = args.get("capability_tier")
        if type(tier) is not int or tier not in {1, 2, 3}:
            raise ValueError("主模型能力判断须为 1–3")
        if args.get("metadata_digest") != result["telemetry"]["report_digest"]:
            raise ValueError("评分引用的元数据版本不匹配")
        routing = result["routing"]
        return {"capability_id": "agent.evaluate", "review": {
            "delegation_id": op["decision_id"], "result_digest": digest_json(result), "scores": scores,
            "score": round(sum(scores.values()) / 3, 2), "accepted": accepted, "failure_kind": kind,
            "reason": note.strip(), "capability_tier": tier, "metadata_verdict": verdict,
            "metadata_digest": result["telemetry"]["report_digest"],
            "profile_key": profile_key(routing["profile"]), "profile_id": routing["profile"]["id"],
            "task_type": routing["task_type"], "difficulty": routing["difficulty"],
            "reviewer": {"provider": turn["settings"]["provider"], "model": (turn.get("control") or {}).get("model") or turn["settings"]["model"]},
            "rubric_version": "pool-review-v2", "evidence_level": "model_judgment"}}

    def resolve(self, turn, args):
        """主模型自行补做拒收任务，保存替代正文与来源；这仍是模型产物，不升级独立验收。"""
        op = self._target(turn, args.get("delegation_id"))
        reviews = [x["result"]["review"] for x in self.repository.operations(turn["run_id"])
                   if (x.get("result") or {}).get("review", {}).get("delegation_id") == op["decision_id"]]
        if not reviews or reviews[-1]["accepted"]:
            raise ValueError("只有已拒收结果需要主模型替代")
        content = args.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > 12000:
            raise ValueError("替代内容必须为 1–12000 字符")
        refs = args.get("evidence_refs", [])
        if not isinstance(refs, list) or any(x not in self.execution._available_subagent_source_refs(turn) for x in refs):
            raise ValueError("替代内容的来源必须已有真实观察")
        ref = self.runtime.objects.put(content.encode())
        return {"capability_id": "agent.resolve", "summary": content[:1200], "resolution": {
            "delegation_id": op["decision_id"], "kind": "parent_replacement", "content_ref": ref,
            "evidence_refs": refs, "evidence_level": "model_output"}}
