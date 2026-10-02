"""可复现演示策略：不调用 LLM，仍经过同一票据、工具和目标验收链。

只执行提交时提供的精确替换规则；用于安装验收和 UI 演示，不能作为
真实模型协议或自然语言推理能力的证据。
"""
import json
from ..models import ModelResult, ProviderStatus


class ScriptedPatchProvider:
    provider_id = "scripted"

    def check(self):
        return ProviderStatus(self.provider_id, True, "none", {"models": ["exact-patch-demo"], "mode": "deterministic demo"})

    def invoke(self, request):
        user = json.loads(request.messages[-1].content)
        context = json.loads(user["context"])
        rules = context["acceptance"]["rules"]
        history = context["history"]
        patches = context["tool_evidence"]
        reads = [n for n in history if n["kind"] == "tool_result" and n["payload"]["capability_id"] == "file.read"]
        base = {"reason": "Follow the fixed exact replacement contract.", "capability_id": "",
                "arguments_json": "{}", "question": "", "missing_info_category": "",
                "claim": "", "goal_coverage": "", "evidence_refs": [], "remaining": []}
        if not rules:
            payload = {**base, "decision_type": "ask_user", "question": "请新建任务并提供固定的精确替换验收规则。"}
        elif len(patches) < len(rules):
            rule = rules[len(patches)]
            if not any(n["payload"]["source_file"] == rule["path"] for n in reads):
                payload = {**base, "decision_type": "tool_call", "capability_id": "file.read",
                           "arguments_json": json.dumps({"path": rule["path"], "offset": 0, "limit": 3000})}
            else:
                payload = {**base, "decision_type": "tool_call", "capability_id": "file.patch_exact",
                           "arguments_json": json.dumps(rule)}
        else:
            latest = {p["source_file"]: p["evidence_ref"] for p in patches}
            payload = {**base, "decision_type": "request_completion", "claim": "已按固定规则完成替换，受管文件通过完整内容验收。",
                       "goal_coverage": "All submitted exact replacement rules.", "evidence_refs": list(latest.values())}
        return ModelResult(json.dumps(payload, ensure_ascii=False), {"model_calls": 1, "input_tokens": 0, "output_tokens": 0},
                           {"mode": "deterministic-demo", "decision": payload})
