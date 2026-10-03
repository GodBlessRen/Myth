"""回归边界：算术/知识路由反例。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.evaluation_runner import FoundationEvalRunner
from myth.models import ModelResult, ProviderStatus
from myth.runtime import MythRuntime
from myth.strategies.intent_pick import RuleIntentPicker
from myth.workspace import Workspace


# 算术/知识路由反例的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class Provider:
    provider_id = "ollama"

    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self):
        self.calls = []

    # 固定返回替身连接状态；只隔离传输，不证明真实供应商可用。
    def check(self):
        return ProviderStatus("ollama", True, details={"models": ["test"]})

    # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
    def invoke(self, request):
        self.calls.append(request)
        return ModelResult(
            json.dumps(
                {
                    "action": "reply",
                    "reason": "fallback model path",
                    "claim": "由模型继续处理",
                },
                ensure_ascii=False,
            ),
            {"model_calls": 1, "input_tokens": 20, "output_tokens": 10},
            {},
        )


# 算术/知识路由反例的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class IntentCorrectnessTests(unittest.TestCase):
    # 回归断言：日期、版本等算术形状碰撞反例不能误进捷径。
    def test_shape_collisions_do_not_enter_deterministic_route(self):
        picker = RuleIntentPicker()
        for text in (
            "2024-10-03",
            "12/31",
            "100%",
            "3.12-1",
            "650-555-1212",
            "1/2",
            "2026/10/03",
            "1.2.3",
        ):
            with self.subTest(text=text):
                self.assertEqual(picker.pick(text, {}).route.value, "agent")

    # 回归断言：明确算术请求允许白名单运算，仍拒绝任意 AST。
    def test_explicit_arithmetic_prefix_admits_ambiguous_operators(self):
        picker = RuleIntentPicker()
        for text in ("计算 2024-10-03", "算一下 12/31", "calc 10%3"):
            with self.subTest(text=text):
                self.assertEqual(picker.pick(text, {}).route.value, "deterministic")
        self.assertEqual(picker.pick("计算 100%", {}).route.value, "agent")

    # 回归断言：模糊知识词需实际召回支持，不能单凭关键字改路由。
    def test_weak_knowledge_words_need_actual_retrieval_strength(self):
        picker = RuleIntentPicker()
        weak = {"sources": [{"score": 0.2, "content": "unrelated"}]}
        for text in (
            "帮我看下 source code 怎么写",
            "文档怎么写比较好",
            "docs 的排版建议是什么",
        ):
            with self.subTest(text=text):
                self.assertEqual(picker.pick(text, weak).route.value, "agent")
        strong = {"sources": [{"score": 1.5, "content": "matching"}]}
        self.assertEqual(
            picker.pick("帮我看文档里的接口", strong).route.value,
            "local_retrieval",
        )

    # 回归断言：规则求值拒绝留事件并走模型回退，不能伪造确定性结果。
    def test_calculate_rejection_records_route_fallback_and_uses_model(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace = Workspace(runtime)
            workspace.repository.save_settings(
                {
                    "provider": "ollama",
                    "model": "test",
                    "ollama_url": "http://127.0.0.1:11434",
                    "max_steps": 6,
                    "max_output_tokens": 512,
                    "thinking": False,
                }
            )
            sid = workspace.repository.create_session()["id"]
            rid = workspace.repository.create_turn(
                sid,
                "计算 2+3",
                "v016-calc-fallback",
            )["run_id"]
            provider = Provider()
            with patch(
                "myth.adapters.conversation_execution.calculate",
                side_effect=ValueError("synthetic calculator rejection"),
            ):
                workspace.run(rid, provider)

            turn = workspace.repository.turn(rid)
            self.assertEqual(turn["status"], "COMPLETED")
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(
                turn["snapshot"]["route_fallbacks"][0]["route"],
                "deterministic->agent",
            )
            events = workspace.repository.events(rid)
            fallback = [item for item in events if item["kind"] == "RouteFallback"]
            self.assertEqual(len(fallback), 1)
            self.assertIn(
                "synthetic calculator rejection", fallback[0]["payload"]["reason"]
            )

    # 回归断言：当前固定集包含形状碰撞反例，并通过真实纯策略执行测量。
    def test_foundation_v4_contains_and_passes_adversarial_intent_set(self):
        suite = Path(__file__).resolve().parents[1] / "evals" / "foundation-v4.json"
        runner = FoundationEvalRunner.from_path(suite)
        adversarial = [
            case.case_id
            for case in runner.suite.cases
            if case.category == "intent_adversarial"
        ]
        self.assertGreaterEqual(len(adversarial), 30)
        result = runner.run(adversarial)
        self.assertEqual(result["report"]["fail_count"], 0)
        self.assertEqual(result["report"]["unsupported_count"], 0)
        self.assertTrue(
            all(item["verdict"] == "PASS" for item in result["observations"])
        )


if __name__ == "__main__":
    unittest.main()
