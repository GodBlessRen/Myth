"""回归边界：模型准入、收据和决定绑定。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.decision_runtime import DecisionRuntime, MAX_SERIALIZED_REQUEST_BYTES
from myth.session_statistics import context_cost_calibration
from myth.acceptance import ContextBudgetError
from myth.models import (
    ContextTruncated,
    ModelMessage,
    ModelRequest,
    ModelResult,
    ProviderStatus,
    STEP_DECISION_SCHEMA,
)
from myth.runtime import MythRuntime


# 模型准入、收据和决定绑定的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class FakeProvider:
    provider_id = "fake"

    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    # 固定返回替身连接状态；只隔离传输，不证明真实供应商可用。
    def check(self) -> ProviderStatus:
        return ProviderStatus(self.provider_id, True, auth_type="none")

    # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
    def invoke(self, request) -> ModelResult:
        if self.fail:
            raise RuntimeError("connection lost after dispatch")
        payload = {
            "decision_type": "tool_call",
            "reason": "The explicit file can be patched.",
            "capability_id": "file.patch_exact",
            "arguments_json": json.dumps(
                {
                    "path": "data.txt",
                    "old_text": "foo",
                    "new_text": "bar",
                    "expected_count": 1,
                }
            ),
            "question": "",
            "missing_info_category": "",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        return ModelResult(
            text=json.dumps(payload),
            usage={"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            raw={
                "id": "fake-response",
                "provider": "fake",
                "model": "fake-model",
                "status": "completed",
                "created_at": 123456,
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 30,
                    "input_tokens_details": {"cached_tokens": 5},
                    "output_tokens_details": {"reasoning_tokens": 7},
                },
                "provider_only_metric": {"lane": "fast"},
                "payload": payload,
            },
            response_id="fake-response",
        )


# 模型准入、收据和决定绑定的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class DecisionRuntimeTests(unittest.TestCase):
    # 回归断言：模型输出工具决定只是提案，必须经过 Runtime Ticket 才能执行。
    def test_model_tool_call_is_only_a_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "data.txt"
            target.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="replace foo with bar in data.txt",
                    provider_id="fake",
                    model_id="fake-model",
                    allowed_files=(target,),
                    max_output_tokens=100,
                )
                decision_id, decision = decisions.request_decision(
                    run_id=run_id,
                    provider=FakeProvider(),
                    model="fake-model",
                    allowed_files=(target,),
                    max_output_tokens=100,
                )
                status = decisions.status(run_id)
                self.assertTrue(decision_id.startswith("dec_"))
                self.assertEqual(decision.decision_type, "tool_call")
                self.assertEqual(status["run"]["state"], "RUNNING")
                self.assertEqual(target.read_text(encoding="utf-8"), "foo")
                self.assertEqual(
                    base.store.db.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                    0,
                )
                accounts = {row["meter"]: row for row in status["budgets"]}
                self.assertEqual(accounts["model_calls"]["settled"], 1)
                self.assertEqual(accounts["input_tokens"]["settled"], 20)
                self.assertEqual(accounts["output_tokens"]["settled"], 30)


    # 回归断言：完整 Provider Evidence 保留在不可变对象中，常用字段则投影成轻量摘要。
    def test_provider_evidence_is_durable_and_lazily_projected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="inspect provider evidence",
                    provider_id="fake",
                    model_id="fake-model",
                    max_output_tokens=100,
                )
                decisions.request_decision(
                    run_id=run_id,
                    provider=FakeProvider(),
                    model="fake-model",
                    max_output_tokens=100,
                )
                status = decisions.status(run_id)
                summary = status["model_invocations"][0]["provider_evidence"]
                self.assertEqual(summary["provider"], "fake")
                self.assertEqual(summary["model"], "fake-model")
                self.assertEqual(summary["cached_input_tokens"], 5)
                self.assertEqual(summary["reasoning_tokens"], 7)
                self.assertIn("provider_only_metric", summary["extra_keys"])

                evidence = decisions.provider_evidence(run_id)
                self.assertEqual(
                    evidence["evidence"]["provider_only_metric"], {"lane": "fast"}
                )
                self.assertEqual(evidence["summary"]["response_id"], "fake-response")

    # 回归断言：Conversation Context 投影与真实 Provider cache 用量绑定成持久观测；缺测字段不补零。
    def test_context_cost_observation_binds_provider_usage_to_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="observe context cost",
                    provider_id="fake",
                    model_id="fake-model",
                    max_output_tokens=100,
                )
                provider = FakeProvider()
                original_invoke = provider.invoke

                # 只扩充固定夹具的公开 usage；模型决定正文仍复用同一合法 wire。
                def invoke(request):
                    value = original_invoke(request)
                    return ModelResult(
                        value.text,
                        {
                            **value.usage,
                            "cached_input_tokens": 8,
                            "cache_write_input_tokens": 4,
                        },
                        value.raw,
                        value.response_id,
                    )

                provider.invoke = invoke
                request = ModelRequest(
                    model="fake-model",
                    messages=(
                        ModelMessage("system", "system"),
                        ModelMessage("user", "goal"),
                    ),
                    response_schema=STEP_DECISION_SCHEMA,
                    max_output_tokens=100,
                    context_report={
                        "context_mode": "compact",
                        "previous_context_mode": "normal",
                        "bytes_used": 1200,
                    },
                )
                decisions.request_decision(
                    run_id=run_id,
                    provider=provider,
                    model="fake-model",
                    max_output_tokens=100,
                    model_request_override=request,
                )
                events = decisions.status(run_id)["events"]
                observed = next(
                    item["payload"]
                    for item in events
                    if item["kind"] == "ConversationContextCostObserved"
                )
                self.assertEqual(observed["context_mode"], "compact")
                self.assertTrue(observed["mode_changed"])
                self.assertEqual(observed["provider_visible_bytes"], 1200)
                self.assertEqual(observed["input_tokens"], 20)
                self.assertEqual(observed["cached_input_tokens"], 8)
                self.assertEqual(observed["cache_write_input_tokens"], 4)
                self.assertAlmostEqual(observed["cache_reuse_ratio"], 0.4)

    # 大窗口要求 Context 预算与完整请求持久化预算一致；超旧 64 KiB 的合法请求仍经过唯一 Ticket。
    def test_large_verified_context_is_admitted_and_measured(self) -> None:
        """固定 90 KiB 请求经真实 Ticket 与收据结算，序列化大小绑定同一 Attempt 的两条事件。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            decisions = DecisionRuntime(runtime)
            rid = decisions.create_goal_run(
                goal="large context preflight", provider_id="fake",
                model_id="fake-model", max_output_tokens=100,
            )
            large = "L" * 90_000
            request = ModelRequest(
                model="fake-model",
                messages=(ModelMessage("system", "system"), ModelMessage("user", large)),
                response_schema=STEP_DECISION_SCHEMA, max_output_tokens=100,
                context_report={
                    "bytes_used": len(large) + len("system"),
                    "max_bytes": 256_000,
                    "model_budget_source": "provider-preflight-frozen-conservative",
                },
            )
            decisions.request_decision(
                run_id=rid, provider=FakeProvider(), model="fake-model",
                max_output_tokens=100, model_request_override=request,
            )
            status = decisions.status(rid)
            compiled = next(
                event["payload"] for event in status["events"]
                if event["kind"] == "ConversationContextCompiled"
            )
            cost = next(
                event["payload"] for event in status["events"]
                if event["kind"] == "ConversationContextCostObserved"
            )
            actual = len(json.dumps(
                request.serializable(), ensure_ascii=False, sort_keys=True,
            ).encode("utf-8"))
            self.assertGreater(actual, 65_536)
            self.assertEqual(compiled["serialized_request_bytes"], actual)
            self.assertEqual(compiled["serialized_request_cap_bytes"], MAX_SERIALIZED_REQUEST_BYTES)
            self.assertEqual(cost["serialized_request_bytes"], actual)
            self.assertEqual(cost["input_tokens"], 20)
            self.assertEqual(len(status["model_invocations"]), 1)
            result = context_cost_calibration(status["events"], status["model_invocations"])
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(result["groups"][0]["paired_samples"], 1)
            self.assertEqual(result["groups"][0]["serialized_request_bytes"], actual)
            self.assertFalse(result["safe_to_expand_context_budget"])

    # 固定存储上限仍必须在任何模型 Ticket 前拒绝，避免大窗口变成无限请求对象。
    def test_hard_request_storage_limit_fails_before_ticket(self) -> None:
        """超 512 KiB 请求不能留下模型机会、收据或 UNKNOWN 预算，不得先调用供应商。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            decisions = DecisionRuntime(runtime)
            rid = decisions.create_goal_run(
                goal="oversized request", provider_id="fake",
                model_id="fake-model", max_output_tokens=100,
            )
            request = ModelRequest(
                model="fake-model",
                messages=(ModelMessage("user", "X" * MAX_SERIALIZED_REQUEST_BYTES),),
                response_schema=STEP_DECISION_SCHEMA,
                max_output_tokens=100,
            )
            with self.assertRaises(ContextBudgetError):
                decisions.request_decision(
                    run_id=rid, provider=FakeProvider(fail=True),
                    model="fake-model", max_output_tokens=100,
                    model_request_override=request,
                )
            state = decisions.status(rid)
            self.assertEqual(state["model_invocations"], [])
            self.assertFalse(any(
                event["kind"] == "ModelTicketGranted" for event in state["events"]
            ))
            self.assertTrue(all(
                row["unknown_held"] == 0 for row in state["budgets"]
            ))

    # 已报告缓存 Token 大于输入 Token 时，只能保留来源字段并拒绝计算非法的命中率。
    def test_invalid_cache_ratio_is_not_reported(self) -> None:
        """供应商用量内部矛盾不得产生大于一的缓存命中率。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            decisions = DecisionRuntime(runtime)
            rid = decisions.create_goal_run(
                goal="check cache measurement", provider_id="fake",
                model_id="fake-model", max_output_tokens=100,
            )
            provider = FakeProvider()
            original = provider.invoke
            def invalid_cache(request):
                """用合法模型提案制造不合法缓存计量，验证不会污染 Context Cost 比率。"""
                result = original(request)
                return ModelResult(
                    result.text, {**result.usage, "cached_input_tokens": 21},
                    result.raw, result.response_id,
                )
            provider.invoke = invalid_cache
            request = ModelRequest(
                "fake-model", (ModelMessage("user", "hello"),),
                STEP_DECISION_SCHEMA, max_output_tokens=100,
                context_report={"bytes_used": 5},
            )
            decisions.request_decision(
                run_id=rid, provider=provider, model="fake-model",
                max_output_tokens=100, model_request_override=request,
            )
            cost = next(
                event["payload"] for event in decisions.status(rid)["events"]
                if event["kind"] == "ConversationContextCostObserved"
            )
            self.assertIsNone(cost["cache_reuse_ratio"])

    # 回归断言：Ticket 后传输异常保持未知，不把超时当作已知未执行。
    def test_provider_exception_after_ticket_becomes_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="decide what to do",
                    provider_id="fake",
                    model_id="fake-model",
                    max_output_tokens=50,
                )
                with self.assertRaises(RuntimeError):
                    decisions.request_decision(
                        run_id=run_id,
                        provider=FakeProvider(fail=True),
                        model="fake-model",
                        max_output_tokens=50,
                    )
                status = decisions.status(run_id)
                self.assertEqual(status["model_invocations"][0]["state"], "UNKNOWN")
                accounts = {row["meter"]: row for row in status["budgets"]}
                self.assertEqual(accounts["model_calls"]["unknown_held"], 1)
                self.assertGreater(accounts["input_tokens"]["unknown_held"], 0)
                self.assertEqual(accounts["output_tokens"]["unknown_held"], 50)

    # 回归断言：已收到明确截断响应属于已知失败，保留实际计量。
    def test_provider_confirmed_truncation_is_failed_not_unknown(self) -> None:
        # 模型准入、收据和决定绑定的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class TruncatedProvider:
            provider_id = "fake"

            # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
            def invoke(self, request):
                raise ContextTruncated(
                    "prompt reached context ceiling",
                    usage={"model_calls": 1, "input_tokens": 40, "output_tokens": 3},
                    raw={"prompt_eval_count": 40, "eval_count": 3},
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="decide what to do",
                    provider_id="fake",
                    model_id="fake-model",
                    max_output_tokens=50,
                )
                with self.assertRaises(ContextBudgetError):
                    decisions.request_decision(
                        run_id=run_id,
                        provider=TruncatedProvider(),
                        model="fake-model",
                        max_output_tokens=50,
                    )
                status = decisions.status(run_id)
                invocation = status["model_invocations"][0]
                self.assertEqual(invocation["state"], "RESOLVED")
                self.assertEqual(invocation["outcome"], "FAILED")
                accounts = {row["meter"]: row for row in status["budgets"]}
                self.assertEqual(accounts["model_calls"]["unknown_held"], 0)
                self.assertEqual(accounts["input_tokens"]["settled"], 40)
                self.assertEqual(accounts["output_tokens"]["settled"], 3)
                events = [item["kind"] for item in status["events"]]
                self.assertIn("ModelAttemptFailed", events)


if __name__ == "__main__":
    unittest.main()
