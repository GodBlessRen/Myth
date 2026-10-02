"""Context pressure must not turn optional recall into a failed user task."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.acceptance import ContextBudgetError
from myth.conversation import conversation_request
from myth.domain import canonical_json
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS = {"provider": "ollama", "model": "test", "max_output_tokens": 512}


class ConversationContextTests(unittest.TestCase):
    def compile(self, snapshot, activities=(), control=None, settings=None):
        return conversation_request(
            settings or SETTINGS, snapshot, snapshot["messages"], list(activities), control=control,
        )

    def test_optional_memory_cannot_crowd_out_current_task(self):
        snapshot = {
            "messages": [{"role": "user", "content": "CURRENT-TASK"}],
            "memory": [
                {"memory_id": f"m{i}", "text": f"MEMORY-{i} " + "旧资料" * 880,
                 "source_ref": f"run:{i}", "revision": 1}
                for i in range(6)
            ],
        }
        request = self.compile(snapshot)
        text = str(request.serializable())
        self.assertIn("CURRENT-TASK", text)
        self.assertIn("MEMORY-0", text)
        self.assertTrue(request.context_report["dropped"])
        self.assertLessEqual(request.context_report["bytes_used"], 42000)

    def test_old_git_and_search_results_fold_but_latest_remains_exact(self):
        snapshot = {"messages": [{"role": "user", "content": "inspect repository"}]}
        activities = [
            {"step": 1, "capability": "git.diff", "decision_id": "d1",
             "result": {"output": "OLD-DIFF\n" + "a" * 24000}},
            {"step": 2, "capability": "knowledge.search", "decision_id": "d2",
             "result": {"sources": [{"citation": "doc:d:0", "content": "b" * 24000}]}},
            {"step": 3, "capability": "project.read", "decision_id": "d3",
             "result": {"content": "LATEST-EVIDENCE", "digest": "fixed-hash", "next_offset": 15}},
        ]
        original = copy.deepcopy(activities)
        request = self.compile(snapshot, activities)
        text = "\n".join(m.content for m in request.messages)
        self.assertIn("LATEST-EVIDENCE", text)
        self.assertIn("fixed-hash", text)
        self.assertIn("doc:d:0", text)
        self.assertIn("d1", text)
        self.assertNotIn("a" * 24000, text)
        self.assertEqual(activities, original)

    def test_compact_keeps_original_task_and_all_current_clarifications(self):
        snapshot = {
            "turn_message_start": 2,
            "messages": [{"role": "user", "content": "OLD-CHAT"},
                         {"role": "assistant", "content": "OLD-ANSWER"},
                         {"role": "user", "content": "ORIGINAL-GOAL"}]
                        + [{"role": "assistant" if i % 2 == 0 else "user",
                            "content": f"CLARIFICATION-{i}"} for i in range(10)],
        }
        request = self.compile(snapshot, control={"compact_requested": True, "revision": 4})
        text = "\n".join(m.content for m in request.messages)
        self.assertIn("ORIGINAL-GOAL", text)
        for i in range(10):
            self.assertIn(f"CLARIFICATION-{i}", text)
        self.assertTrue(request.context_report["compact_requested"])

    def test_pinned_attachment_survives_recall_pressure(self):
        snapshot = {
            "messages": [{"role": "user", "content": "summarize attachment"}],
            "attached_document_ids": ["pin"],
            "knowledge": [
                {"document_id": str(i), "citation": f"doc:{i}:0", "title": "retrieved",
                 "content": "资料" * 2900} for i in range(5)
            ] + [{"document_id": "pin", "citation": "doc:pin:0", "title": "attached",
                  "content": "PINNED-EVIDENCE"}],
        }
        request = self.compile(snapshot)
        self.assertIn("PINNED-EVIDENCE", "\n".join(m.content for m in request.messages))
        self.assertIn("knowledge:doc:pin:0", request.context_report["selected"])

    def test_required_content_is_never_silently_cut(self):
        for snapshot, activities in [
            ({"project": {"instructions": "x" * 42000},
              "messages": [{"role": "user", "content": "task"}]}, []),
            ({"messages": [{"role": "user", "content": "task"}]},
             [{"step": 1, "result": {"content": "文" * 15000}}]),
        ]:
            with self.subTest(snapshot=snapshot.keys()), self.assertRaises(ContextBudgetError):
                self.compile(snapshot, activities)

    def test_compact_limits_only_history_and_preserves_generated_artifact(self):
        snapshot = {
            "turn_message_start": 20,
            "messages": [{"role": "user", "content": f"OLD-{i}"} for i in range(20)]
                        + [{"role": "user", "content": "CURRENT-GOAL"}],
        }
        activities = [
            {"step": 1, "result": {"artifact": {"name": "plan.md", "digest": "immutable"},
                                   "evidence_ref": "artifact:write@immutable"}},
            {"step": 2, "result": {"content": "latest"}},
        ]
        request = self.compile(snapshot, activities, {"compact_requested": True})
        self.assertEqual(len([ref for ref in request.context_report["selected"] if ref.startswith("message:")]), 9)
        self.assertIn("artifact:write@immutable", str(request.serializable()))
        self.assertIn("message:0", request.context_report["dropped"])

    def test_accounting_includes_json_escaping_roles_and_remote_instructions(self):
        snapshot = {"messages": [{"role": "user", "content": "\\\"\n文" * 1800}]}
        for provider in ("ollama", "openai", "pi-openai"):
            request = self.compile(snapshot, settings={**SETTINGS, "provider": provider})
            serialized = request.serializable()
            actual = len(json.dumps(serialized["messages"], ensure_ascii=False, sort_keys=True).encode("utf-8"))
            self.assertEqual(request.context_report["bytes_used"], actual)
            self.assertLessEqual(actual, 42000)
            self.assertLessEqual(len(json.dumps(serialized, ensure_ascii=False).encode("utf-8")), 65536)
            self.assertEqual(request.serializable(), self.compile(snapshot, settings={**SETTINGS, "provider": provider}).serializable())


class ConversationContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.temp.name))
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings(SETTINGS)
        self.sid = self.repo.create_session()["id"]
        self.rid = self.repo.create_turn(self.sid, "read then answer", "first")["run_id"]

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

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

    def test_compact_arriving_in_flight_applies_to_next_model_request(self):
        provider = ChatProvider([decision("tool_call", "math.calculate", {"expression": "2+3"}), decision()])
        invoke = provider.invoke

        def while_in_flight(request):
            if not provider.calls:
                self.workspace.control.command(self.rid, "compact")
            return invoke(request)

        provider.invoke = while_in_flight
        self.workspace.run(self.rid, provider)
        self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
        self.assertTrue(provider.calls[1].context_report["compact_requested"])
        events = [e for e in self.repo.events(self.rid) if e["kind"] == "ContextCompactionConsumed"]
        self.assertEqual(len(events), 1)

    def test_replayed_receipt_does_not_acknowledge_new_compact_command(self):
        class Crash(BaseException):
            pass

        provider = ChatProvider([decision("tool_call", "math.calculate", {"expression": "2+3"}), decision()])
        with patch.object(self.repo, "bind", side_effect=Crash):
            with self.assertRaises(Crash):
                self.workspace.run(self.rid, provider)
        self.workspace.control.command(self.rid, "compact")
        self.workspace.run(self.rid, provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(provider.calls[1].context_report["compact_requested"])
        events = [e for e in self.repo.events(self.rid) if e["kind"] == "ConversationContextCompiled"]
        self.assertEqual(len(events), 2)

    def test_two_large_tool_outputs_complete_with_original_receipts_intact(self):
        provider = ChatProvider([
            decision("tool_call", "git.diff"),
            decision("tool_call", "git.diff"),
            decision(),
        ])
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

    def test_context_event_matches_immutable_request_and_survives_reopen(self):
        self.workspace.run(self.rid, ChatProvider())
        events = [e for e in self.repo.events(self.rid) if e["kind"] == "ConversationContextCompiled"]
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        request = json.loads(self.runtime.objects.get(payload["request_ref"]))
        for key, value in request["context_report"].items():
            self.assertEqual(payload[key], value)
        with MythRuntime(Path(self.temp.name)) as runtime:
            saved = Workspace(runtime).repository.events(self.rid)
            self.assertEqual(events, [e for e in saved if e["kind"] == "ConversationContextCompiled"])

    def test_context_failure_has_no_model_ticket_or_compiled_event(self):
        turn = self.repo.turn(self.rid)
        turn["snapshot"]["project"] = {"instructions": "X" * 42000}
        with self.runtime.store.tx() as db:
            db.execute("UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",
                       (canonical_json(turn["snapshot"]), self.rid))
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.repo.turn(self.rid)["status"], "FAILED")
        self.assertFalse(any(e["kind"] in {"ModelTicketGranted", "ConversationContextCompiled"}
                             for e in self.repo.events(self.rid)))

    def test_legacy_snapshot_infers_current_turn_boundary_without_rewriting(self):
        turn = self.repo.turn(self.rid)
        snapshot = turn["snapshot"]
        snapshot.pop("turn_message_start")
        snapshot.pop("attached_document_ids")
        snapshot["messages"] = [{"role": "user", "content": f"old-{i}"} for i in range(12)] + snapshot["messages"]
        stored = canonical_json(snapshot)
        with self.runtime.store.tx() as db:
            db.execute("UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?", (stored, self.rid))
        turn = self.repo.turn(self.rid)
        self.assertEqual(turn["snapshot"]["turn_message_start"], 12)
        self.workspace.control.command(self.rid, "compact")
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertIn("read then answer", str(provider.calls[0].serializable()))
        self.assertEqual(self.runtime.store.db.execute(
            "SELECT snapshot_json FROM workspace_turns WHERE run_id=?", (self.rid,),
        ).fetchone()[0], stored)


if __name__ == "__main__":
    unittest.main()
