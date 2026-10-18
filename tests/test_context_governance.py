"""Context Governance 纯策略与真实 Conversation 编译回归。"""

import unittest
from pathlib import Path
import tempfile
import subprocess
import sys
import json
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.web_workspace import ConversationWebService

from myth.acceptance import ContextBudgetError
from myth.conversation import conversation_request
from myth.platform.context_governance import build_causal_guard, lexical_relevance
from myth.model_capabilities import remote_context_budget


SETTINGS = {
    "provider": "ollama", "model": "test", "max_output_tokens": 512,
    "num_ctx": 8192, "temperature": 0.0,
}


class ContextGovernanceTests(unittest.TestCase):
    """验证因果状态不会被相关性、预算或来源推测静默覆盖。"""

    def test_causal_guard_only_uses_reported_status_and_explicit_edges(self):
        """仅已记录关键结果与显式依赖进入保护链；未记录关系保持缺失。"""
        activities = [
            {"step": 1, "decision_id": "prepare", "capability": "project.read",
             "result": {"content": "input"}},
            {"step": 2, "decision_id": "write", "capability": "artifact.write",
             "declared_dependencies": ["prepare", "missing-op"],
             "result": {"status": "UNKNOWN", "evidence_ref": "attempt:2"}},
            {"step": 3, "decision_id": "review", "capability": "test.run",
             "result": {"status": "PASSED"}},
        ]
        guard = build_causal_guard(activities)
        self.assertEqual(guard["critical_count"], 1)
        self.assertEqual([row["source"] for row in guard["records"]],
                         ["activity:1", "activity:2"])
        self.assertEqual(guard["missing_declared_dependencies"], ["missing-op"])
        self.assertIsNone(build_causal_guard([activities[0], activities[2]]))

    def test_bounded_lexical_relevance_is_only_a_ranking_hint(self):
        """词面重合只改变可选候选排序，不证明因果或事实等级。"""
        self.assertGreater(
            lexical_relevance("fix payment timeout", "payment timeout logs"),
            lexical_relevance("fix payment timeout", "unrelated astronomy"),
        )

    def test_compaction_keeps_causal_guard_and_reports_provenance(self):
        """强制 Compact 仍保留状态导航与来源摘要，不能吞掉 UNKNOWN。"""
        snapshot = {
            "messages": [{"role": "user", "content": "核对支付后再决定是否重试"}],
            "memory": [{"memory_id": "m1", "text": "无关资料" * 4000}],
        }
        activities = [
            {"step": 1, "decision_id": "pay-1", "capability": "mcp.call",
             "result": {"status": "UNKNOWN", "error": "transport timeout"}},
            {"step": 2, "decision_id": "read-2", "capability": "knowledge.search",
             "result": {"content": "unrelated"}},
        ]
        request = conversation_request(
            SETTINGS, snapshot, snapshot["messages"], activities,
            control={"compact_requested": True},
        )
        content = "\n".join(msg.content for msg in request.messages)
        self.assertIn("UNKNOWN", content)
        self.assertIn("pay-1", content)
        self.assertIn("causal-guard", request.context_report["selected"])
        self.assertEqual(request.context_report["governance"]["causal_critical_count"], 1)
        self.assertTrue(request.context_report["governance"]["causal_guard_selected"])

    def test_required_causal_guard_fails_closed_when_budget_exhausted(self):
        """固定预算容纳不了关键状态时停止模型请求而不是静默截断。"""
        from myth.conversation_context import compile_conversation_context
        snapshot = {"messages": [{"role": "user", "content": "task"}]}
        activities = [
            {"step": i, "decision_id": f"op-{i}", "capability": "mcp.call",
             "result": {"status": "UNKNOWN"}}
            for i in range(100)
        ]
        with self.assertRaises(ContextBudgetError):
            compile_conversation_context(
                "system", snapshot, snapshot["messages"], activities,
                max_bytes=200, compact_mode=True,
            )


    def test_structured_failure_and_parallel_children_are_protected(self):
        """已记录的结构化失败与并行子结果需要进入同一状态导航。"""
        guard = build_causal_guard([
            {"step": 1, "decision_id": "base", "result": {"content": "sample"}},
            {"step": 2, "decision_id": "batch", "capability": "agent.parallel",
             "result": {"results": [
                 {"delegation_id": "child-1", "status": "FAILED",
                  "handoff": {"depends_on": ["base"]}},
                 {"delegation_id": "child-2", "status": "COMPLETED"},
             ]}},
        ])
        self.assertEqual(guard["critical_count"], 1)
        self.assertEqual([item["source"] for item in guard["records"]],
                         ["activity:1", "activity:2"])
        self.assertEqual(guard["records"][-1]["child_delegation_ids"],
                         ["child-1", "child-2"])
        self.assertIn("child_0:FAILED", guard["records"][-1]["reported_outcomes"])
        self.assertEqual(guard["missing_declared_dependencies"], [])
        failure = build_causal_guard([{
            "step": 3, "decision_id": "write",
            "result": {"failure": {"code": "permission_denied", "retryable": False}},
        }])
        self.assertIn("known_failure:permission_denied",
                      failure["records"][0]["reported_outcomes"])

    def test_relevance_prefers_matching_memory_only_when_both_do_not_fit(self):
        """保留原权威来源和用户任务，在预算压力下优先选择词面相关的可选记忆。"""
        snapshot = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "memory": [
                {"memory_id": "old", "text": "astronomy " * 1600},
                {"memory_id": "important", "text": "payment timeout " * 800},
            ],
        }
        request = conversation_request(SETTINGS, snapshot, snapshot["messages"], [])
        selected = request.context_report["selected"]
        self.assertIn("memory:important@", " ".join(selected))
        self.assertNotIn("memory:old@", " ".join(selected))

    def test_relevant_memory_can_outrank_unrelated_knowledge(self):
        """两种已准入检索来源在同一量尺排序，相关 Memory 不被无关 Knowledge 压制。"""
        snapshot = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "knowledge": [{"document_id": "unrelated", "citation": "doc:u:0",
                           "title": "astronomy", "content": "astronomy " * 1600}],
            "memory": [{"memory_id": "relevant",
                        "text": "payment timeout " * 800}],
        }
        request = conversation_request(
            SETTINGS, snapshot, snapshot["messages"], [],
        )
        selected = request.context_report["selected"]
        self.assertIn("memory:relevant@", " ".join(selected))
        self.assertNotIn("knowledge:doc:u:0", selected)
        self.assertEqual(request.context_report["delivered"]["memory"], 1)
        self.assertEqual(request.context_report["delivered"]["knowledge"], 0)

    def test_web_send_freezes_provider_window_and_replays_same_intent(self):
        """真实准入持久化公开模型窗口，重复 request_id 不再依赖当前目录或网络。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                repository = Workspace(runtime).repository
                repository.save_settings({
                    "provider": "openai", "model": "fixture",
                    "max_output_tokens": 1024,
                })
                sid = repository.create_session()["id"]
            web = ConversationWebService(root)
            web.model_catalog.quote_settings = lambda settings: settings
            web._spawn = lambda run_id: None
            profile = {
                "id": "fixture", "provider": "openai",
                "context_window": 65536, "source": "provider-preflight",
            }
            calls = []
            def preflight(settings, *, entry):
                """离线预检替身记录请求次数；不联网也不授予执行权。"""
                calls.append(entry)
                return profile
            web._require_model_preflight = preflight
            first = web.send(sid, {"text": "Explain timeout", "request_id": "fixed"})
            with MythRuntime(root) as runtime:
                turn = Workspace(runtime).repository.turn(first["run_id"])
            self.assertEqual(turn["settings"]["admitted_model_profile"], profile)
            self.assertEqual(turn["settings"]["model"], "fixture")
            second = web.send(sid, {"text": "Explain timeout", "request_id": "fixed"})
            self.assertEqual(first, second)
            self.assertEqual(calls, ["send"])

    def test_controlled_mechanisms_change_real_context_behavior(self):
        """真实 Context 编译验证全开、全关、单项开启的差异，不用标签伪造消融。"""
        from myth.evaluation_runner import CONTROLLED_HARNESS_MECHANISMS
        from myth.conversation_context import compile_conversation_context
        self.assertIn("context_causal_guard", CONTROLLED_HARNESS_MECHANISMS)
        self.assertIn("context_relevance_ranking", CONTROLLED_HARNESS_MECHANISMS)
        original = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "knowledge": [{"document_id": "unrelated", "citation": "doc:u:0",
                           "title": "astronomy", "content": "astronomy " * 1250}],
            "memory": [{"memory_id": "relevant",
                        "text": "payment timeout " * 650}],
        }
        activities = [{"step": 1, "decision_id": "attempt-1",
                       "result": {"status": "UNKNOWN", "error": "timeout"}}]
        def compile_with(enabled):
            """隔离同一输入下的一组机制，使所选内容的变化可直接比较。"""
            snapshot = {**original, "evaluation_harness_mechanisms": list(enabled)}
            return compile_conversation_context(
                "test", snapshot, snapshot["messages"], activities,
                max_bytes=15_000,
            )[1]
        baseline = compile_with(())
        full = compile_with(("context_causal_guard", "context_relevance_ranking"))
        only_causal = compile_with(("context_causal_guard",))
        only_relevance = compile_with(("context_relevance_ranking",))
        self.assertNotIn("causal-guard", baseline["selected"])
        self.assertIn("causal-guard", full["selected"])
        self.assertIn("causal-guard", only_causal["selected"])
        self.assertNotIn("causal-guard", only_relevance["selected"])
        self.assertIn("knowledge:doc:u:0", baseline["selected"])
        self.assertIn("memory:relevant@", " ".join(full["selected"]))
        self.assertIn("memory:relevant@", " ".join(only_relevance["selected"]))

    def test_unresolved_runtime_ledgers_survive_missing_step_result(self):
        """直接构造崩溃窗口的持久账本：无步骤结果时依然保护 UNKNOWN，结算后恢复为零风险。"""
        from myth.conversation_context import compile_conversation_context
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            workspace = Workspace(runtime)
            repo = workspace.repository
            repo.save_settings(SETTINGS)
            sid = repo.create_session()["id"]
            rid = repo.create_turn(sid, "Explain what happened", "ledger-guard")["run_id"]
            # 夹具直接写入 SQLite 模拟工具收据未落库时的断电状态；生产不得绕过正式 Ticket。
            with runtime.store.tx() as db:
                db.execute(
                    "INSERT INTO workspace_operations "
                    "(decision_id,run_id,capability,state,intent_json,ticket_id,reserved_bytes) "
                    "VALUES(?,?,?,'UNKNOWN','{}',?,0)",
                    ("tool-pending", rid, "artifact.write", "ctkt-pending"),
                )
                db.execute(
                    "UPDATE workspace_execution_cursors SET phase='OUTCOME_UNKNOWN', "
                    "recovery_state='RECONCILE' WHERE run_id=?", (rid,),
                )
                db.execute(
                    "UPDATE accounts SET unknown_held=1 WHERE run_id=? AND meter='write_bytes'",
                    (rid,),
                )
            liabilities = repo.context_liabilities(rid)
            self.assertEqual(liabilities["operations"][0]["state"], "UNKNOWN")
            turn = repo.turn(rid)
            snapshot = {**turn["snapshot"], "runtime_liabilities": liabilities}
            messages, report = compile_conversation_context(
                "system", snapshot, snapshot["messages"], [],
                max_bytes=16_000,
            )
            joined = "\n".join(item.content for item in messages)
            self.assertIn("runtime-tool:tool-pending", joined)
            self.assertIn("runtime-budget:write_bytes", joined)
            self.assertIn("runtime-cursor", joined)
            self.assertIn("causal-guard", report["selected"])
            self.assertEqual(report["governance"]["causal_runtime_protected"], 3)
            # 同一个真实 Execution.seam 编译模型请求，但替换 Ticket 协调器以防夹具制造新模型效果。
            with patch.object(
                repo.decisions, "request_decision",
                side_effect=lambda **kwargs: kwargs["model_request_override"],
            ) as request_dispatch:
                request = workspace.execution.decide(repo.turn(rid), 1, object())
            self.assertTrue(request_dispatch.called)
            self.assertIn("runtime-tool:tool-pending", "\n".join(m.content for m in request.messages))
            self.assertIn("causal-guard", request.context_report["selected"])
            self.assertEqual(request.context_report["governance"]["causal_runtime_protected"], 3)
            self.assertFalse(any(
                event["kind"] == "ModelTicketGranted" for event in repo.events(rid)
            ))
            with runtime.store.tx() as db:
                db.execute(
                    "UPDATE workspace_operations SET state='RESOLVED',result_json='{}' "
                    "WHERE decision_id='tool-pending'",
                )
                db.execute(
                    "UPDATE workspace_execution_cursors SET phase='TOOL_RECORDED', "
                    "recovery_state='NONE' WHERE run_id=?", (rid,),
                )
                db.execute(
                    "UPDATE accounts SET unknown_held=0 WHERE run_id=? AND meter='write_bytes'",
                    (rid,),
                )
            current = repo.context_liabilities(rid)
            self.assertIn("tool-pending", current["settled_tool_decisions"])
            clean = build_causal_guard([], current)
            self.assertIsNone(clean)

    def test_active_set_limits_historical_failures_but_never_drops_open_unknown(self):
        """80 次已知失败只保留最近 8 次，未决 UNKNOWN 和它的旧前驱永远不能丢。"""
        from myth.platform.context_governance import render_causal_guard
        activities = [
            {"step": i, "decision_id": f"done-{i}",
             "capability": "test.run", "result": {"status": "FAILED"}}
            for i in range(80)
        ]
        activities.append({
            "step": 80, "decision_id": "open-tool",
            "declared_dependencies": ["done-0"],
            "capability": "artifact.write", "result": {"status": "UNKNOWN"},
        })
        guard = build_causal_guard(activities)
        self.assertEqual(guard["active_risk_count"], 1)
        self.assertEqual(guard["recent_issue_count"], 8)
        self.assertEqual(guard["archived_issue_count"], 71)
        self.assertEqual(guard["critical_count"], 9)
        self.assertEqual(len(guard["records"]), 10)
        self.assertEqual(guard["records"][0]["role"], "declared_predecessor")
        self.assertEqual(guard["records"][-1]["role"], "active_risk")
        self.assertEqual(guard["records"][0]["decision_id"], "done-0")
        text, digest = render_causal_guard(guard)
        self.assertIn("open-tool", text)
        self.assertLess(len(text.encode("utf-8")), 6000)
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(guard["archived_issue_digest"]), 64)

    def test_runtime_receipt_retires_stale_activity_unknown_not_child_unknown(self):
        """同 Run RESOLVED 只校准原工具 UNKNOWN，不能凭父收据消除子委派风险。"""
        activities = [
            {"step": 1, "decision_id": "write-1", "result": {"status": "UNKNOWN"}},
        ]
        old = build_causal_guard(activities)
        self.assertEqual(old["active_risk_count"], 1)
        settled = build_causal_guard(
            activities, {"settled_tool_decisions": ["write-1"]}
        )
        self.assertEqual(settled["active_risk_count"], 0)
        self.assertEqual(settled["recent_issue_count"], 1)
        self.assertIn("runtime_tool:RESOLVED", settled["records"][0]["reported_outcomes"])
        self.assertIn("historical_tool_report:UNKNOWN", settled["records"][0]["reported_outcomes"])
        child = build_causal_guard(
            [{"step": 2, "decision_id": "parent",
              "result": {"status": "UNKNOWN", "results": [
                  {"delegation_id": "sub-1", "status": "UNKNOWN"}
              ]}}],
            {"settled_tool_decisions": ["parent"]},
        )
        self.assertEqual(child["active_risk_count"], 1)
        self.assertIn("child_0:UNKNOWN", child["records"][0]["reported_outcomes"])

    def test_invalid_runtime_identity_fails_closed(self):
        """未结算状态身份无法安全表示时明确拒绝，不应为节省 Token 直接删除。"""
        with self.assertRaises(ValueError):
            build_causal_guard([], {"operations": [
                {"decision_id": "bad secret with whitespace", "state": "UNKNOWN"}
            ]})
        with self.assertRaises(ValueError):
            build_causal_guard([], {"models": [
                {"model_attempt_id": "m1", "state": "RESOLVED"}
            ]})

    def test_remote_window_provenance_blocks_adapter_family_guess(self):
        """模型名推测的窗口不冒充 Provider 实测；真正来源声明需要两层一致。"""
        from myth.providers.openai import _openai_model_capability
        self.assertEqual(
            _openai_model_capability("gpt-5.6-claim")["source"],
            "adapter-family-rule",
        )
        with tempfile.TemporaryDirectory() as tmp:
            web = ConversationWebService(Path(tmp))
            settings = {"provider": "openai", "model": "fixture", "max_output_tokens": 512}
            profile = {"id": "fixture", "context_window": 65536, "source": "adapter-family-rule"}
            def mocked_connection(_settings):
                """仅固定公开预检结果，用来核对来源而非访问真实网络。"""
                return {"ready": True, "provider": "openai", "details": {
                    "models": ["fixture"], "model_capabilities": {"fixture": profile},
                    "capability_source": "provider",
                }}
            web.connection = mocked_connection
            self.assertIsNone(web._require_model_preflight(settings, entry="send"))
            profile["source"] = "provider"
            frozen = web._require_model_preflight(settings, entry="send")
            self.assertEqual(frozen["context_window"], 65536)
            self.assertEqual(frozen["source"], "provider-preflight")

    def test_remote_budget_reserves_pessimistic_token_density(self):
        """在短窗口下，即使输入接近单字节单 Token 也保留输出与协议余量。"""
        settings = {
            "provider": "openai", "model": "fixture", "max_output_tokens": 1024,
            "admitted_model_profile": {
                "provider": "openai", "id": "fixture", "context_window": 8192,
                "source": "provider-preflight",
            },
        }
        result = remote_context_budget(settings)
        self.assertEqual(result["max_bytes"], 8192 - 1024 - 512 - 2048)
        self.assertLess(result["max_bytes"], 8192 - 1024 - 512)
        settings["admitted_model_profile"]["context_window"] = 3000
        with self.assertRaises(ValueError):
            remote_context_budget(settings)

    def test_controlled_eval_cli_is_reproducible_without_provider(self):
        """公开 CLI 使用固定 Suite 运行四组真实机制切换，不请求模型也不自动写评测账本。"""
        root = Path(__file__).resolve().parent.parent
        process = subprocess.run(
            [
                sys.executable, "-m", "myth.cli", "eval-controlled",
                "--suite", str(root / "evals" / "context-governance-v1.json"),
                "--mechanism", "context_causal_guard",
                "--mechanism", "context_relevance_ranking",
            ],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stderr[-3000:])
        output = json.loads(process.stdout)
        self.assertEqual(output["evaluation_partition"], "discovery")
        self.assertEqual(len(output["runs"]), 4)
        self.assertTrue(all(r["complete_suite"] for r in output["runs"]))
        self.assertTrue(all(
            obs["metrics"].get("model_calls", 0) == 0
            for run in output["runs"] for obs in run["observations"]
        ))

    def test_fixed_suite_proves_mechanism_specific_ablation(self):
        """五道固定 Context 题运行全关/单机制/全开，任务结论必须来自真实编译结果。"""
        from myth.evaluation_runner import run_controlled_harness_experiment
        suite = Path(__file__).resolve().parent.parent / "evals" / "context-governance-v1.json"
        matrix = run_controlled_harness_experiment(
            suite, ("context_causal_guard", "context_relevance_ranking"),
            prefix="context-fixture-v1",
        )
        self.assertEqual(len(matrix), 4)
        outcomes = {
            frozenset(run["harness_mechanisms"]): {
                item["case_id"]: item["verdict"] for item in run["observations"]
            }
            for run in matrix
        }
        full = frozenset({"context_causal_guard", "context_relevance_ranking"})
        self.assertTrue(all(value == "PASS" for value in outcomes[full].values()))
        none = outcomes[frozenset()]
        self.assertEqual(none["context-no-false-positive"], "PASS")
        self.assertEqual(none["causal-open-ledger"], "FAIL")
        self.assertEqual(none["context-cross-source-relevance"], "FAIL")
        self.assertEqual(outcomes[frozenset({"context_causal_guard"})]["causal-predecessor"], "PASS")
        self.assertEqual(outcomes[frozenset({"context_causal_guard"})]["context-cross-source-relevance"], "FAIL")
        self.assertEqual(outcomes[frozenset({"context_relevance_ranking"})]["context-cross-source-relevance"], "PASS")
        self.assertEqual(outcomes[frozenset({"context_relevance_ranking"})]["context-guard-fail-closed"], "FAIL")
        self.assertTrue(all(run["evaluation_partition"] == "discovery" for run in matrix))

    def test_remote_model_window_requires_frozen_matching_preflight(self):
        """仅身份匹配的冻结公开窗口可以扩大远端软预算，切换模型立即退回保守上限。"""
        remote = {"provider": "openai", "model": "fixture", "max_output_tokens": 1024}
        profile = {"id": "fixture", "provider": "openai",
                   "context_window": 65536, "source": "provider-preflight"}
        budget = remote_context_budget({**remote, "admitted_model_profile": profile})
        self.assertEqual(budget["window_tokens"], 65536)
        self.assertGreater(budget["max_bytes"], 42_000)
        self.assertEqual(remote_context_budget({
            **remote, "model": "another", "admitted_model_profile": profile,
        })["max_bytes"], 42_000)
        self.assertEqual(remote_context_budget(remote)["max_bytes"], 42_000)
        snapshot = {"messages": [{"role": "user", "content": "hello"}]}
        req = conversation_request(
            {**remote, "admitted_model_profile": profile},
            snapshot, snapshot["messages"], [],
        )
        self.assertEqual(req.context_report["max_bytes"], budget["max_bytes"])
        self.assertEqual(req.context_report["declared_model_context_window"], 65536)
        self.assertEqual(req.context_report["model_budget_source"],
                         "provider-preflight-frozen-conservative")


if __name__ == "__main__":
    unittest.main()
