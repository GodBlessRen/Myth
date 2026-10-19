"""FRAMEBREAKER 冻结态四臂材料实验：只编译请求，不访问 Provider/Runtime 状态。"""

import unittest

from myth.conversation import build_context_request
from myth.models import ModelMessage, ModelRequest
from myth.platform.context_materiality import (
    CONTEXT_BENCHMARK_ARMS, frozen_context_material_probe, model_visible_digest,
)


class FrozenContextMaterialityTests(unittest.TestCase):
    """控制本地审计元数据与模型可见内容的差异，测试因果对照不夸大证据。"""

    # 使用真实 ModelRequest 合同生成规范输入，不以会变化的报告字段制造差异。
    @staticmethod
    def request(text, *, report=None):
        return ModelRequest(
            model="test-model",
            messages=(ModelMessage("user", text),),
            response_schema={"type": "object"},
            max_output_tokens=128,
            context_report=report or {},
        )

    # 仅修改本地 context_report 不能被认成模型确实收到了不同 Prompt。
    def test_report_metadata_does_not_count_as_material_difference(self):
        a = self.request("same words", report={"causality": "enabled"})
        b = self.request("same words", report={"causality": "disabled"})
        self.assertEqual(model_visible_digest(a), model_visible_digest(b))
        probe = frozen_context_material_probe(
            a, list(CONTEXT_BENCHMARK_ARMS["context-full"]),
            lambda mechanisms: self.request("same words", report={"mechanisms": mechanisms}),
        )
        self.assertEqual(probe["status"], "FROZEN_COMPILER_MEASURED")
        self.assertFalse(any(probe["material_contrasts"].values()))
        self.assertFalse(probe["provider_wire_verified"])
        self.assertFalse(probe["causal_attribution"])

    # 正控：同一编译输入下两个开关确实改变模型消息时，记录四个准确的方向差分。
    def test_both_switches_materially_change_model_input(self):
        def compile_arm(mechanisms):
            enabled = set(mechanisms)
            return self.request(
                "shared task"
                + (" | unresolved effect" if "context_causal_guard" in enabled else "")
                + (" | relevant excerpt" if "context_relevance_ranking" in enabled else "")
            )
        actual = compile_arm(CONTEXT_BENCHMARK_ARMS["context-full"])
        probe = frozen_context_material_probe(
            actual, list(CONTEXT_BENCHMARK_ARMS["context-full"]), compile_arm,
        )
        self.assertEqual(probe["actual_visible_digest"], model_visible_digest(actual))
        self.assertTrue(all(probe["material_contrasts"].values()))
        self.assertEqual(len(set(probe["variant_visible_digests"].values())), 4)

    # 同一机制配置的影子再编译应产生完全相同的模型输入；若不等，不能冒充因果测量。
    def test_current_shadow_mismatch_is_unverified(self):
        probe = frozen_context_material_probe(
            self.request("original"), list(CONTEXT_BENCHMARK_ARMS["context-full"]),
            lambda mechanisms: self.request("changed between calls"),
        )
        self.assertEqual(probe["status"], "UNVERIFIED")
        self.assertEqual(probe["reason"], "current_request_differs_from_shadow")

    # 影子分支的上下文溢出或错误必须显式缺测，但不得阻止当前正常模型机会。
    def test_shadow_compile_failure_does_not_raise(self):
        def invalid(_mechanisms):
            raise ValueError("private message should not be copied to benchmark report")
        probe = frozen_context_material_probe(
            self.request("actual"), list(CONTEXT_BENCHMARK_ARMS["context-baseline"]),
            invalid,
        )
        self.assertEqual(probe["status"], "UNVERIFIED")
        self.assertEqual(probe["reason"], "shadow_compilation_failed")
        self.assertEqual(probe["exception_type"], "ValueError")
        self.assertNotIn("private message", str(probe))

    # 用真实 Conversation Context 编译器证明开放 UNKNOWN 的因果保护确实改变模型材料。
    def test_real_context_compiler_causal_liability_changes_prompt(self):
        settings = {
            "provider": "ollama", "model": "test-model",
            "num_ctx": 8192, "max_output_tokens": 128, "max_steps": 4,
        }
        snapshot = {
            "turn_message_start": 0,
            "runtime_liabilities": {
                "operations": [{
                    "decision_id": "decision-example", "ticket_id": "ticket-example",
                    "capability": "artifact.write", "state": "UNKNOWN",
                }],
                "models": [], "unknown_held": [], "settled_tool_decisions": [],
            },
        }
        messages = [{"role": "user", "content": "继续核对未知执行结果"}]

        def compile_arm(mechanisms):
            return build_context_request(
                settings,
                {**snapshot, "evaluation_harness_mechanisms": list(mechanisms)},
                messages, [], system="相同系统指令", schema={"type": "object"},
            )

        actual = compile_arm(CONTEXT_BENCHMARK_ARMS["context-full"])
        probe = frozen_context_material_probe(
            actual, list(CONTEXT_BENCHMARK_ARMS["context-full"]), compile_arm,
        )
        self.assertEqual(probe["status"], "FROZEN_COMPILER_MEASURED")
        self.assertTrue(probe["material_contrasts"]["causal_without_relevance"])
        self.assertTrue(probe["material_contrasts"]["causal_with_relevance"])
        self.assertFalse(probe["material_contrasts"]["relevance_without_causal"])


if __name__ == "__main__":
    unittest.main()
