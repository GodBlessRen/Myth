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


class Provider:
    provider_id="ollama"

    def __init__(self):
        self.calls=[]

    def check(self):
        return ProviderStatus("ollama",True,details={"models":["test"]})

    def invoke(self,request):
        self.calls.append(request)
        return ModelResult(
            json.dumps({
                "action":"reply",
                "reason":"fallback model path",
                "claim":"由模型继续处理",
            },ensure_ascii=False),
            {"model_calls":1,"input_tokens":20,"output_tokens":10},
            {},
        )


class IntentCorrectnessTests(unittest.TestCase):
    def test_shape_collisions_do_not_enter_deterministic_route(self):
        picker=RuleIntentPicker()
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
                self.assertEqual(picker.pick(text,{}).route.value,"agent")

    def test_explicit_arithmetic_prefix_admits_ambiguous_operators(self):
        picker=RuleIntentPicker()
        for text in ("计算 2024-10-03","算一下 12/31","calc 10%3"):
            with self.subTest(text=text):
                self.assertEqual(picker.pick(text,{}).route.value,"deterministic")
        self.assertEqual(picker.pick("计算 100%",{}).route.value,"agent")

    def test_weak_knowledge_words_need_actual_retrieval_strength(self):
        picker=RuleIntentPicker()
        weak={"sources":[{"score":0.2,"content":"unrelated"}]}
        for text in ("帮我看下 source code 怎么写","文档怎么写比较好","docs 的排版建议是什么"):
            with self.subTest(text=text):
                self.assertEqual(picker.pick(text,weak).route.value,"agent")
        strong={"sources":[{"score":1.5,"content":"matching"}]}
        self.assertEqual(
            picker.pick("帮我看文档里的接口",strong).route.value,
            "local_retrieval",
        )

    def test_calculate_rejection_records_route_fallback_and_uses_model(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            workspace=Workspace(runtime)
            workspace.repository.save_settings({
                "provider":"ollama",
                "model":"test",
                "ollama_url":"http://127.0.0.1:11434",
                "max_steps":6,
                "max_output_tokens":512,
                "thinking":False,
            })
            sid=workspace.repository.create_session()["id"]
            rid=workspace.repository.create_turn(
                sid,
                "计算 2+3",
                "v016-calc-fallback",
            )["run_id"]
            provider=Provider()
            with patch(
                "myth.adapters.conversation_execution.calculate",
                side_effect=ValueError("synthetic calculator rejection"),
            ):
                workspace.run(rid,provider)

            turn=workspace.repository.turn(rid)
            self.assertEqual(turn["status"],"COMPLETED")
            self.assertEqual(len(provider.calls),1)
            self.assertEqual(
                turn["snapshot"]["route_fallbacks"][0]["route"],
                "deterministic->agent",
            )
            events=workspace.repository.events(rid)
            fallback=[item for item in events if item["kind"]=="RouteFallback"]
            self.assertEqual(len(fallback),1)
            self.assertIn("synthetic calculator rejection",fallback[0]["payload"]["reason"])

    def test_foundation_v4_contains_and_passes_adversarial_intent_set(self):
        suite=Path(__file__).resolve().parents[1]/"evals"/"foundation-v4.json"
        runner=FoundationEvalRunner.from_path(suite)
        adversarial=[case.case_id for case in runner.suite.cases if case.category=="intent_adversarial"]
        self.assertGreaterEqual(len(adversarial),30)
        result=runner.run(adversarial)
        self.assertEqual(result["report"]["fail_count"],0)
        self.assertEqual(result["report"]["unsupported_count"],0)
        self.assertTrue(all(item["verdict"]=="PASS" for item in result["observations"]))


if __name__=="__main__":
    unittest.main()
