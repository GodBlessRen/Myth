"""回归边界：有界上下文与 Compact revision 消费。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.acceptance import ContextBudgetError
from myth.conversation import conversation_request
from myth.domain import canonical_json
from myth.platform.context_anchor import build_context_anchor
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "max_output_tokens": 512,
    "num_ctx": 16384,
    "temperature": 0.0,
}


# 有界上下文与 Compact revision 消费的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ConversationContextTests(unittest.TestCase):
    # 有界上下文与 Compact revision 消费的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def compile(self, snapshot, activities=(), control=None, settings=None):
        return conversation_request(
            settings or SETTINGS,
            snapshot,
            snapshot["messages"],
            list(activities),
            control=control,
        )

    # 回归断言：可选旧记忆不能挤掉当前任务和硬约束。
    def test_optional_memory_cannot_crowd_out_current_task(self):
        snapshot = {
            "messages": [{"role": "user", "content": "CURRENT-TASK"}],
            "memory": [
                {
                    "memory_id": f"m{i}",
                    "text": f"MEMORY-{i} " + "旧资料" * 880,
                    "source_ref": f"run:{i}",
                    "revision": 1,
                }
                for i in range(6)
            ],
        }
        request = self.compile(snapshot)
        text = str(request.serializable())
        self.assertIn("CURRENT-TASK", text)
        self.assertIn("MEMORY-0", text)
        self.assertTrue(request.context_report["dropped"])
        self.assertLessEqual(request.context_report["bytes_used"], 42000)

    # 回归断言：折叠旧工具展示保留来源，最新工具结果继续精确进入请求。
    def test_old_git_and_search_results_fold_but_latest_remains_exact(self):
        snapshot = {"messages": [{"role": "user", "content": "inspect repository"}]}
        activities = [
            {
                "step": 1,
                "capability": "git.diff",
                "decision_id": "d1",
                "result": {"output": "OLD-DIFF\n" + "a" * 24000},
            },
            {
                "step": 2,
                "capability": "test.run",
                "decision_id": "test-old",
                "result": {
                    "status": "FAILED",
                    "stdout": "TEST-STDOUT-" + "z" * 12000,
                    "stderr": "TEST-STDERR-" + "y" * 12000,
                    "evidence_ref": "test:profile@digest",
                },
            },
            {
                "step": 3,
                "capability": "knowledge.search",
                "decision_id": "d2",
                "result": {
                    "sources": [{"citation": "doc:d:0", "content": "b" * 24000}]
                },
            },
            {
                "step": 4,
                "capability": "project.read",
                "decision_id": "d3",
                "result": {
                    "content": "LATEST-EVIDENCE",
                    "digest": "fixed-hash",
                    "next_offset": 15,
                },
            },
        ]
        original = copy.deepcopy(activities)
        request = self.compile(snapshot, activities)
        text = "\n".join(m.content for m in request.messages)
        self.assertIn("LATEST-EVIDENCE", text)
        self.assertIn("fixed-hash", text)
        self.assertIn("doc:d:0", text)
        self.assertIn("d1", text)
        self.assertIn("observation.read", text)
        self.assertIn('"decision_id":"d1"', text)
        self.assertIn('"decision_id":"test-old"', text)
        self.assertNotIn("z" * 12000, text)
        self.assertNotIn("y" * 12000, text)
        self.assertNotIn("a" * 24000, text)
        self.assertEqual(request.context_report["projection"]["recall_capability"], "observation.read")
        self.assertEqual(
            request.context_report["fold_reason"]["reason_code"],
            "older_observation_preview",
        )
        self.assertEqual(activities, original)

    # 回归断言：Compact 仍保留当前任务全部澄清，不能以压缩改意图。
    def test_compact_keeps_original_task_and_all_current_clarifications(self):
        snapshot = {
            "turn_message_start": 2,
            "messages": [
                {"role": "user", "content": "OLD-CHAT"},
                {"role": "assistant", "content": "OLD-ANSWER"},
                {"role": "user", "content": "ORIGINAL-GOAL"},
            ]
            + [
                {
                    "role": "assistant" if i % 2 == 0 else "user",
                    "content": f"CLARIFICATION-{i}",
                }
                for i in range(10)
            ],
        }
        request = self.compile(
            snapshot, control={"compact_requested": True, "revision": 4}
        )
        text = "\n".join(m.content for m in request.messages)
        self.assertIn("ORIGINAL-GOAL", text)
        for i in range(10):
            self.assertIn(f"CLARIFICATION-{i}", text)
        self.assertTrue(request.context_report["compact_requested"])
        self.assertEqual(request.context_report["compaction_seed"]["source"], "durable-facts")
        self.assertTrue(request.context_report["compaction_seed"]["selected"])
        self.assertEqual(request.context_report["context_mode"], "compact")
        self.assertTrue(request.context_report["compact_applied"])
        self.assertEqual(
            request.context_report["context_decision"]["reason_code"],
            "explicit_user_control",
        )

    # 回归断言：高窗口压力且已有持久语义边界时，Context 自动选择紧凑投影；这不是用户 Compact 命令。
    def test_context_auto_compacts_only_after_settled_boundary_under_pressure(self):
        snapshot = {
            "turn_message_start": 18,
            "messages": [
                {"role": "user", "content": f"OLD-{i}-" + ("历史" * 650)}
                for i in range(18)
            ]
            + [{"role": "user", "content": "CURRENT-GOAL"}],
        }
        activities = [
            {
                "step": 1,
                "capability": "test.run",
                "decision_id": "verify-1",
                "result": {
                    "status": "PASSED",
                    "evidence_ref": "test:profile@digest",
                },
            }
        ]
        request = self.compile(
            snapshot,
            activities,
            settings={**SETTINGS, "num_ctx": 8192},
        )
        self.assertEqual(request.context_report["context_mode"], "compact")
        self.assertTrue(request.context_report["compact_applied"])
        self.assertFalse(request.context_report["compact_requested"])
        self.assertEqual(
            request.context_report["context_decision"]["reason_code"],
            "context_pressure",
        )
        self.assertGreater(
            request.context_report["context_decision"]["provider_visible_saving_bytes"],
            0,
        )
        self.assertGreater(
            request.context_report["compaction_seed"]["semantic_boundaries"],
            0,
        )

    # 回归断言：大量召回不能挤掉显式固定附件。
    def test_pinned_attachment_survives_recall_pressure(self):
        snapshot = {
            "messages": [{"role": "user", "content": "summarize attachment"}],
            "attached_document_ids": ["pin"],
            "knowledge": [
                {
                    "document_id": str(i),
                    "citation": f"doc:{i}:0",
                    "title": "retrieved",
                    "content": "资料" * 2900,
                }
                for i in range(5)
            ]
            + [
                {
                    "document_id": "pin",
                    "citation": "doc:pin:0",
                    "title": "attached",
                    "content": "PINNED-EVIDENCE",
                }
            ],
        }
        request = self.compile(snapshot)
        self.assertIn("PINNED-EVIDENCE", "\n".join(m.content for m in request.messages))
        self.assertIn("knowledge:doc:pin:0", request.context_report["selected"])

    # 回归断言：必需资料过大提前失败，不能原始字符串截断后照常调用。
    def test_required_content_is_never_silently_cut(self):
        for snapshot, activities in [
            (
                {
                    "project": {"instructions": "x" * 42000},
                    "messages": [{"role": "user", "content": "task"}],
                },
                [],
            ),
            (
                {"messages": [{"role": "user", "content": "task"}]},
                [{"step": 1, "result": {"content": "文" * 15000}}],
            ),
        ]:
            with (
                self.subTest(snapshot=snapshot.keys()),
                self.assertRaises(ContextBudgetError),
            ):
                self.compile(snapshot, activities)

    # 回归断言：压缩历史展示仍保留已生成产物身份，避免重复生成。
    def test_compact_limits_only_history_and_preserves_generated_artifact(self):
        snapshot = {
            "turn_message_start": 20,
            "messages": [{"role": "user", "content": f"OLD-{i}"} for i in range(20)]
            + [{"role": "user", "content": "CURRENT-GOAL"}],
        }
        activities = [
            {
                "step": 1,
                "result": {
                    "artifact": {"name": "plan.md", "digest": "immutable"},
                    "evidence_ref": "artifact:write@immutable",
                },
            },
            {"step": 2, "result": {"content": "latest"}},
        ]
        request = self.compile(snapshot, activities, {"compact_requested": True})
        self.assertEqual(
            len(
                [
                    ref
                    for ref in request.context_report["selected"]
                    if ref.startswith("message:")
                ]
            ),
            9,
        )
        self.assertIn("artifact:write@immutable", str(request.serializable()))
        self.assertIn("message:0", request.context_report["dropped"])

    # 回归断言：字节预算包括传输角色、转义和指令，不能只算正文。
    def test_accounting_includes_json_escaping_roles_and_remote_instructions(self):
        snapshot = {"messages": [{"role": "user", "content": '\\"\n文' * 1800}]}
        for provider in ("ollama", "openai", "pi-openai"):
            request = self.compile(
                snapshot, settings={**SETTINGS, "provider": provider}
            )
            serialized = request.serializable()
            actual = len(
                json.dumps(
                    serialized["messages"], ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            )
            self.assertEqual(request.context_report["bytes_used"], actual)
            self.assertLessEqual(actual, 42000)
            self.assertLessEqual(
                len(json.dumps(serialized, ensure_ascii=False).encode("utf-8")), 65536
            )
            self.assertEqual(
                request.serializable(),
                self.compile(
                    snapshot, settings={**SETTINGS, "provider": provider}
                ).serializable(),
            )

    # Anchor 的增量复用必须重新证明 covered prefix；历史正文变化后从真实来源重建。
    def test_context_anchor_rebuilds_when_covered_history_changes(self):
        messages = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(16)
        ]
        first = build_context_anchor(None, messages, cover_count=12)
        changed = copy.deepcopy(messages)
        changed[0]["content"] = "tampered-history"
        rebuilt = build_context_anchor(first, changed, cover_count=12)
        self.assertEqual(first["version"], "extractive-anchor-v2")
        self.assertNotEqual(first["source_digest"], rebuilt["source_digest"])
        self.assertNotEqual(first["digest"], rebuilt["digest"])
        self.assertIn("tampered-history", rebuilt["summary"])


# 有界上下文与 Compact revision 消费的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ConversationContinuityTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.temp.name))
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({**SETTINGS, "num_ctx": 32768})
        self.sid = self.repo.create_session()["id"]
        self.rid = self.repo.create_turn(self.sid, "read then answer", "first")[
            "run_id"
        ]

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    # 回归断言：暂停 Turn 继续占有会话，不能另建工作绕过安全点。
    def test_paused_turn_still_owns_the_session(self):
        self.workspace.control.command(self.rid, "pause")
        with self.assertRaises(ValueError):
            self.repo.create_turn(self.sid, "another task", "second")
        with self.assertRaises(ValueError):
            self.repo.update_session(self.sid, {"archived": True})
        self.assertEqual(len(self.repo.session(self.sid)["turns"]), 1)
        self.workspace.control.command(self.rid, "resume")
        self.workspace.run(self.rid, ChatProvider())
        self.repo.create_turn(self.sid, "next task", "second")

    # 回归断言：在途新增 Compact 留给下一真实请求，不提前消费命令。
    def test_compact_arriving_in_flight_applies_to_next_model_request(self):
        provider = ChatProvider(
            [decision("tool_call", "math.calculate", {"expression": "2+3"}), decision()]
        )
        invoke = provider.invoke

        # 有界上下文与 Compact revision 消费的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def while_in_flight(request):
            if not provider.calls:
                self.workspace.control.command(self.rid, "compact")
            return invoke(request)

        provider.invoke = while_in_flight
        self.workspace.run(self.rid, provider)
        self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
        self.assertTrue(provider.calls[1].context_report["compact_requested"])
        events = [
            e
            for e in self.repo.events(self.rid)
            if e["kind"] == "ContextCompactionConsumed"
        ]
        self.assertEqual(len(events), 1)

    # 回归断言：旧收据/决定重放不清除较新的 Compact revision。
    def test_replayed_receipt_does_not_acknowledge_new_compact_command(self):
        # 有界上下文与 Compact revision 消费的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class Crash(BaseException):
            pass

        provider = ChatProvider(
            [decision("tool_call", "math.calculate", {"expression": "2+3"}), decision()]
        )
        with patch.object(self.repo, "bind", side_effect=Crash):
            with self.assertRaises(Crash):
                self.workspace.run(self.rid, provider)
        self.workspace.control.command(self.rid, "compact")
        self.workspace.run(self.rid, provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(provider.calls[1].context_report["compact_requested"])
        events = [
            e
            for e in self.repo.events(self.rid)
            if e["kind"] == "ConversationContextCompiled"
        ]
        self.assertEqual(len(events), 2)

    # 回归断言：大工具结果通过投影预算处理；原始完整收据/对象仍保存。
    def test_two_large_tool_outputs_complete_with_original_receipts_intact(self):
        provider = ChatProvider(
            [
                decision("tool_call", "git.diff"),
                decision("tool_call", "git.diff"),
                decision(),
            ]
        )
        result = {"output": "diff-line\n" * 2600, "truncated": False}
        with patch.object(self.workspace.execution, "_git", return_value=result):
            self.workspace.run(self.rid, provider)
        self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
        self.assertEqual(len(provider.calls), 3)
        for op in self.repo.operations(self.rid):
            self.assertEqual(op["result"]["output"], result["output"])
        accounts = {a["meter"]: a for a in self.repo.turn(self.rid)["budgets"]}
        self.assertEqual(accounts["model_calls"]["settled"], 3)
        self.assertEqual(accounts["tool_calls"]["settled"], 2)

    # 回归断言：上下文事件对应固定请求对象，重开后来源和字节账一致。
    def test_context_event_matches_immutable_request_and_survives_reopen(self):
        self.workspace.run(self.rid, ChatProvider())
        events = [
            e
            for e in self.repo.events(self.rid)
            if e["kind"] == "ConversationContextCompiled"
        ]
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        request = json.loads(self.runtime.objects.get(payload["request_ref"]))
        for key, value in request["context_report"].items():
            self.assertEqual(payload[key], value)
        with MythRuntime(Path(self.temp.name)) as runtime:
            saved = Workspace(runtime).repository.events(self.rid)
            self.assertEqual(
                events, [e for e in saved if e["kind"] == "ConversationContextCompiled"]
            )

    # 回归断言：请求构造失败前没有 Ticket/已使用 Compact 的伪造事件。
    def test_context_failure_has_no_model_ticket_or_compiled_event(self):
        turn = self.repo.turn(self.rid)
        turn["snapshot"]["project"] = {"instructions": "X" * 70000}
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",
                (canonical_json(turn["snapshot"]), self.rid),
            )
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.repo.turn(self.rid)["status"], "FAILED")
        self.assertFalse(
            any(
                e["kind"] in {"ModelTicketGranted", "ConversationContextCompiled"}
                for e in self.repo.events(self.rid)
            )
        )


    # 首轮建立 epoch；直接延续只复用已证明的 continuity，并进入模型 Context report。
    def test_direct_continuation_resumes_same_epoch(self):
        self.workspace.run(self.rid, ChatProvider())
        first = self.repo.turn(self.rid)["snapshot"]["continuity"]
        self.assertEqual(first["action"], "new")
        second = self.repo.create_turn(self.sid, "next task", "continuity-second")
        current = second["snapshot"]["continuity"]
        self.assertEqual(current["action"], "resume")
        self.assertEqual(current["reason"], "direct_continuation")
        self.assertEqual(current["epoch"], first["epoch"])
        provider = ChatProvider()
        self.workspace.run(second["run_id"], provider)
        self.assertEqual(
            provider.calls[0].context_report["continuity"]["action"], "resume"
        )

    # 模型语义环境变化不继续沿用旧 epoch；rebuild 只重建派生 Context，不删除历史。
    def test_model_change_rebuilds_continuity_epoch(self):
        self.workspace.run(self.rid, ChatProvider())
        first = self.repo.turn(self.rid)["snapshot"]["continuity"]
        self.repo.save_settings({**SETTINGS, "num_ctx": 32768, "model": "test-next"})
        second = self.repo.create_turn(self.sid, "next task", "continuity-model")
        current = second["snapshot"]["continuity"]
        self.assertEqual(current["action"], "rebuild")
        self.assertEqual(current["reason"], "model_changed")
        self.assertEqual(current["epoch"], first["epoch"] + 1)
        self.assertGreater(len(self.repo.session(self.sid)["messages"]), 0)

    # Current Facts 版本独立于 query ranking；权威事实变化会让旧 continuity 失效。
    def test_current_fact_revision_rebuilds_continuity(self):
        self.workspace.run(self.rid, ChatProvider())
        self.workspace.memory.remember(
            kind="semantic",
            text="User now prefers compact answers.",
            source_ref="user:preference",
            fact_level="user_asserted",
        )
        second = self.repo.create_turn(self.sid, "next task", "continuity-facts")
        current = second["snapshot"]["continuity"]
        self.assertEqual(current["action"], "rebuild")
        self.assertEqual(current["reason"], "current_facts_changed")
        self.assertEqual(current["current_facts"]["count"], 1)

    # 消息正文与写入时 digest 不一致时 fail closed；不能把篡改历史当 direct continuation。
    def test_message_body_change_breaks_continuity(self):
        self.workspace.run(self.rid, ChatProvider())
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_messages SET content='tampered' "
                "WHERE run_id=? AND role='user'",
                (self.rid,),
            )
        second = self.repo.create_turn(self.sid, "next task", "continuity-tamper")
        current = second["snapshot"]["continuity"]
        self.assertEqual(current["action"], "rebuild")
        self.assertEqual(current["reason"], "history_message_changed")
        self.assertFalse(current["anchor_reuse"])

    # 旧基线仍在同一分支但漏看额外消息时使用 catchup，不把已证明的 Anchor 无谓丢弃。
    def test_intervening_message_uses_catchup(self):
        self.workspace.run(self.rid, ChatProvider())
        with self.runtime.store.tx() as db:
            self.repo._message(
                db,
                self.sid,
                None,
                "assistant",
                "out-of-band durable note",
                {"kind": "external"},
            )
        second = self.repo.create_turn(self.sid, "next task", "continuity-catchup")
        current = second["snapshot"]["continuity"]
        self.assertEqual(current["action"], "catchup")
        self.assertEqual(current["reason"], "intervening_messages")
        self.assertTrue(current["anchor_reuse"])
        events = [
            event
            for event in self.repo.events(second["run_id"])
            if event["kind"] == "ConversationContinuityPlanned"
        ]
        self.assertEqual(events[-1]["payload"]["action"], "catchup")


if __name__ == "__main__":
    unittest.main()
