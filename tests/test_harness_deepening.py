"""Harness Engineering 四项深化的回归边界。
这些测试固定纯策略与 Conversation 集成语义；替身通过不等同真实模型质量或外部 Provider 保证。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.adapters.workspace_store import SqliteWorkspaceRepository
from myth.conversation import TOOL_CATALOG, conversation_request
from myth.failures import observe_failure
from myth.models import ModelResult, ProviderStatus, StepDecision
from myth.platform.completion import CompletionGuard
from myth.platform.context_anchor import build_context_anchor
from myth.platform.tool_discovery import search_tools, visible_tool_ids
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# 固定模型决定 JSON；字段完整以覆盖真实 StepDecision wire，而不是依赖自由文本解析。
def decision(
    kind="request_completion",
    capability="",
    args=None,
    *,
    claim="done",
    remaining=None,
    evidence_refs=None,
):
    return json.dumps(
        {
            "decision_type": kind,
            "reason": "fixture",
            "capability_id": capability,
            "arguments_json": json.dumps(args or {}),
            "question": "",
            "missing_info_category": "",
            "claim": claim,
            "goal_coverage": "answer",
            "evidence_refs": evidence_refs or [],
            "remaining": remaining or [],
        },
        ensure_ascii=False,
    )


# 最小 Provider 替身；只记录请求并返回固定结果，不模拟真实远端稳定性。
class Provider:
    provider_id = "ollama"

    # 保存预定输出序列；超出长度时复用最后一项，便于发现意外额外调用。
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    # 固定返回本地测试模型可用；这只是夹具连接状态。
    def check(self):
        return ProviderStatus("ollama", True, details={"models": ["test"]})

    # 返回固定 wire；用量仅用于 Runtime 账本回归。
    def invoke(self, request):
        self.calls.append(request)
        value = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
        return ModelResult(
            value,
            {"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            {"fixture": True},
        )


# 四项深化的固定回归集合；每个测试只断言一个长期边界。
class HarnessDeepeningTests(unittest.TestCase):
    # 结构化失败保留稳定机器码与下一步提示，不要求调用方解析人类字符串控制流程。
    def test_structured_failure_observation_classifies_known_denial(self):
        observation = observe_failure(
            ValueError("information control denied: duplicate exact request"),
            capability_id="project.search",
        )
        self.assertEqual(observation.code, "information_control_denied")
        self.assertEqual(observation.category, "context")
        self.assertTrue(observation.retryable)
        self.assertEqual(observation.capability_id, "project.search")
        self.assertIn("continuation", observation.hint)

    # Stop Guard 拒绝模型自己仍声明 remaining 的停止请求；完成声明不能覆盖未完成事实。
    def test_completion_guard_rejects_remaining_work(self):
        verdict = CompletionGuard().evaluate(
            {"activities": [], "snapshot": {}},
            StepDecision(
                decision_type="request_completion",
                reason="fixture",
                claim="done",
                remaining=("run tests",),
            ),
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.observation.code, "completion_remaining")

    # 已执行 verifier 的最新结果若失败，模型不能在下一步直接 request_completion。
    def test_completion_guard_requires_latest_executed_verifier_to_pass(self):
        turn = {
            "snapshot": {},
            "activities": [
                {
                    "decision": {"capability_id": "test.run"},
                    "result": {"status": "FAILED", "evidence_ref": "test:one"},
                }
            ],
        }
        verdict = CompletionGuard().evaluate(
            turn,
            StepDecision(
                decision_type="request_completion",
                reason="fixture",
                claim="done",
            ),
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.observation.code, "verification_not_passed")
        turn["activities"][0]["result"]["status"] = "PASSED"
        self.assertTrue(
            CompletionGuard()
            .evaluate(
                turn,
                StepDecision(
                    decision_type="request_completion",
                    reason="fixture",
                    claim="done",
                    evidence_refs=("test:one",),
                ),
            )
            .allowed
        )

    # Context Anchor 只增量覆盖跨过阈值的旧消息并保持有界；原消息列表仍是 source of truth。
    def test_context_anchor_is_incremental_bounded_projection(self):
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}-" + "x" * 300}
            for i in range(20)
        ]
        original = json.dumps(messages, ensure_ascii=False)
        first = build_context_anchor(None, messages, cover_count=12, max_bytes=2400)
        extended = messages + [
            {"role": "user", "content": "new-20"},
            {"role": "assistant", "content": "new-21"},
        ]
        second = build_context_anchor(first, extended, cover_count=14, max_bytes=2400)
        self.assertEqual(first["covered_messages"], 12)
        self.assertEqual(second["covered_messages"], 14)
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertLessEqual(second["bytes"], 2400)
        self.assertEqual(json.dumps(messages, ensure_ascii=False), original)

    # 延迟工具必须经 search/describe 的 durable Observation 才能进入后续可见集合；失败偷调不会解锁。
    def test_deferred_tool_visibility_cannot_be_bypassed_by_rejected_call(self):
        initial = visible_tool_ids(TOOL_CATALOG, [])
        self.assertNotIn("git.diff", initial)
        failed = [
            {
                "decision": {"capability_id": "git.diff"},
                "result": {"error": "tool is deferred", "failure": {"code": "tool_deferred"}},
            }
        ]
        self.assertNotIn("git.diff", visible_tool_ids(TOOL_CATALOG, failed))
        matches = search_tools(
            TOOL_CATALOG,
            {tool_id: tool_id for tool_id in TOOL_CATALOG},
            "git diff",
        )
        self.assertTrue(any(item["capability_id"] == "git.diff" for item in matches))
        discovered = [
            {
                "decision": {"capability_id": "tool.search"},
                "result": {"matches": matches},
            }
        ]
        self.assertIn("git.diff", visible_tool_ids(TOOL_CATALOG, discovered))

    # Ollama schema 与 Prompt 只暴露当前工具集合；search 结果会让下一步 schema 出现专门工具。
    def test_conversation_request_progressively_expands_ollama_schema(self):
        settings = {
            "provider": "ollama",
            "model": "test",
            "num_ctx": 8192,
            "max_output_tokens": 512,
            "temperature": 0.0,
            "thinking": None,
        }
        snapshot = {
            "project": None,
            "knowledge": [],
            "memory": [],
            "messages": [{"role": "user", "content": "inspect git changes"}],
            "turn_message_start": 0,
        }
        request = conversation_request(
            settings,
            snapshot,
            snapshot["messages"],
            [],
        )
        actions = {
            item["properties"]["action"]["enum"][0]
            for item in request.response_schema["oneOf"]
        }
        self.assertIn("tool.search", actions)
        self.assertNotIn("git.diff", actions)
        activities = [
            {
                "step": 1,
                "decision": {"capability_id": "tool.search"},
                "result": {
                    "matches": [
                        {
                            "capability_id": "git.diff",
                            "description": "Inspect diff",
                            "arguments": {},
                        }
                    ]
                },
            }
        ]
        expanded = conversation_request(
            settings,
            snapshot,
            snapshot["messages"],
            activities,
        )
        expanded_actions = {
            item["properties"]["action"]["enum"][0]
            for item in expanded.response_schema["oneOf"]
        }
        self.assertIn("git.diff", expanded_actions)

    # Conversation 集成把未知能力拒绝写成结构化 Observation；它不产生 Tool Ticket。
    def test_workspace_persists_structured_known_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MythRuntime(Path(tmp)) as runtime:
                workspace = Workspace(runtime)
                repo: SqliteWorkspaceRepository = workspace.repository
                repo.save_settings({"provider": "ollama", "model": "test"})
                sid = repo.create_session()["id"]
                rid = repo.create_turn(sid, "try unsafe tool", "failure-1")["run_id"]
                provider = Provider(
                    [
                        decision("tool_call", "shell.exec", {"command": "bad"}),
                        decision(claim="recovered"),
                    ]
                )
                workspace.run(rid, provider)
                turn = repo.turn(rid)
                self.assertEqual(turn["status"], "COMPLETED")
                failure = turn["activities"][0]["result"]["failure"]
                self.assertEqual(failure["code"], "permission_denied")
                self.assertEqual(turn["activities"][0]["result"]["observation_kind"], "failure")
                self.assertEqual(repo.operations(rid), [])

    # Stop Guard 集成拒绝第一次带 remaining 的 completion，并允许模型在新步骤补完。
    def test_workspace_verify_on_stop_returns_observation_then_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MythRuntime(Path(tmp)) as runtime:
                workspace = Workspace(runtime)
                repo = workspace.repository
                repo.save_settings({"provider": "ollama", "model": "test"})
                sid = repo.create_session()["id"]
                rid = repo.create_turn(sid, "finish carefully", "stop-1")["run_id"]
                provider = Provider(
                    [
                        decision(claim="premature", remaining=["verify"]),
                        decision(claim="verified enough for this fixture"),
                    ]
                )
                workspace.run(rid, provider)
                turn = repo.turn(rid)
                self.assertEqual(turn["status"], "COMPLETED")
                self.assertEqual(len(provider.calls), 2)
                self.assertEqual(
                    turn["activities"][0]["result"]["failure"]["code"],
                    "completion_remaining",
                )
                self.assertEqual(
                    turn["activities"][0]["result"]["observation_kind"],
                    "completion_guard",
                )


if __name__ == "__main__":
    unittest.main()
