"""确定性的模型替身。
按固定精确文件任务提出决策，用来验证 Runtime/验收路径；它没有真实网络推理能力，不得作为模型质量证据。"""

import json
from ..models import ModelResult, ProviderStatus


# Exact 文件任务的确定性模型替身；用于重复验证步骤和收据，不是网络推理后端。
class ScriptedPatchProvider:
    # provider_id：供应商合同身份；必须匹配 Run/Turn 的固定设置。
    provider_id = "scripted"

    # 观察供应商认证/服务是否可用；返回状态而不签发模型 Ticket。
    def check(self):
        return ProviderStatus(
            self.provider_id,
            True,
            "none",
            {"models": ["exact-patch-demo"], "mode": "deterministic demo"},
        )

    # 将已准入统一请求交给具体传输实现，返回模型结果/用量；不拥有业务状态或完成验收。
    def invoke(self, request):
        user = json.loads(request.messages[-1].content)
        context = json.loads(user["context"])
        rules = context["acceptance"]["rules"]
        history = context["history"]
        patches = context["tool_evidence"]
        reads = [
            n
            for n in history
            if n["kind"] == "tool_result"
            and n["payload"]["capability_id"] == "file.read"
        ]
        base = {
            "reason": "Follow the fixed exact replacement contract.",
            "capability_id": "",
            "arguments_json": "{}",
            "question": "",
            "missing_info_category": "",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        if not rules:
            payload = {
                **base,
                "decision_type": "ask_user",
                "question": "请新建任务并提供固定的精确替换验收规则。",
            }
        elif len(patches) < len(rules):
            rule = rules[len(patches)]
            if not any(n["payload"]["source_file"] == rule["path"] for n in reads):
                payload = {
                    **base,
                    "decision_type": "tool_call",
                    "capability_id": "file.read",
                    "arguments_json": json.dumps(
                        {"path": rule["path"], "offset": 0, "limit": 3000}
                    ),
                }
            else:
                payload = {
                    **base,
                    "decision_type": "tool_call",
                    "capability_id": "file.patch_exact",
                    "arguments_json": json.dumps(rule),
                }
        else:
            latest = {p["source_file"]: p["evidence_ref"] for p in patches}
            payload = {
                **base,
                "decision_type": "request_completion",
                "claim": "已按固定规则完成替换，受管文件通过完整内容验收。",
                "goal_coverage": "All submitted exact replacement rules.",
                "evidence_refs": list(latest.values()),
            }
        return ModelResult(
            json.dumps(payload, ensure_ascii=False),
            {"model_calls": 1, "input_tokens": 0, "output_tokens": 0},
            {"mode": "deterministic-demo", "decision": payload},
        )
