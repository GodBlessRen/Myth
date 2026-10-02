from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict
from myth.platform.control import ControlCommand
from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "ollama_url": "http://127.0.0.1:11434",
    "max_steps": 6,
    "max_output_tokens": 512,
    "thinking": False,
}


class RuntimeClosureTests(unittest.TestCase):
    def test_control_revision_allocation_is_atomic_across_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                sid = workspace.repository.create_session("control")["id"]
                turn = workspace.repository.create_turn(sid, "hello", "req-control-race")
                rid = turn["run_id"]
                workspace.control.ensure(rid, turn["settings"])

            barrier = threading.Barrier(2)
            revisions: list[int] = []
            errors: list[BaseException] = []
            lock = threading.Lock()

            def issue(command, payload=None):
                try:
                    with MythRuntime(root) as runtime:
                        workspace = Workspace(runtime)
                        barrier.wait(timeout=5)
                        result = workspace.control.command(rid, command, payload)
                        with lock:
                            revisions.append(result["revision"])
                except BaseException as exc:
                    with lock:
                        errors.append(exc)

            a = threading.Thread(target=issue, args=(ControlCommand.STEER, "focus"))
            b = threading.Thread(target=issue, args=(ControlCommand.COMPACT,))
            a.start()
            b.start()
            a.join(5)
            b.join(5)

            self.assertEqual(errors, [])
            self.assertEqual(sorted(revisions), [2, 3])
            with MythRuntime(root) as runtime:
                history = Workspace(runtime).control.view(rid)["commands"]
                self.assertEqual([item["revision"] for item in history], [2, 3])

    def test_goal_identity_is_admitted_before_turn_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ConversationWebService(root)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                sid = workspace.repository.create_session("goal")["id"]

            with patch.object(
                service,
                "connection",
                return_value={"ready": True, "details": {"models": ["test"]}},
            ):
                with self.assertRaises(KeyError):
                    service.send(
                        sid,
                        {
                            "text": "work on this",
                            "request_id": "req-missing-goal",
                            "goal_id": "goal_missing",
                        },
                    )

            with MythRuntime(root) as runtime:
                self.assertEqual(
                    runtime.store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                    0,
                )

                workspace = Workspace(runtime)
                goal_a = workspace.personal.create_goal("A")
                goal_b = workspace.personal.create_goal("B")
                turn = workspace.repository.create_turn(
                    sid,
                    "same request",
                    "req-goal-identity",
                    goal_id=goal_a["goal_id"],
                )
                self.assertTrue(turn["run_id"])
                with self.assertRaises(IdentityConflict):
                    workspace.repository.create_turn(
                        sid,
                        "same request",
                        "req-goal-identity",
                        goal_id=goal_b["goal_id"],
                    )

    def test_episodic_memory_is_scoped_and_global_memory_remains_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                project_a = workspace.repository.create_project({"name": "A"})
                project_b = workspace.repository.create_project({"name": "B"})
                session_a = workspace.repository.create_session(project_id=project_a["id"])["id"]
                session_b = workspace.repository.create_session(project_id=project_b["id"])["id"]
                run_a = workspace.repository.create_turn(
                    session_a, "alpha", "req-memory-a"
                )["run_id"]
                run_b = workspace.repository.create_turn(
                    session_b, "beta", "req-memory-b"
                )["run_id"]

                memory_a = workspace.memory.record_episode(
                    run_a, "codeword ORBIT-71", "project A answer"
                )
                memory_b = workspace.memory.record_episode(
                    run_b, "codeword ORBIT-71", "project B answer"
                )
                global_memory = workspace.memory.remember(
                    kind="semantic",
                    text="global preference ORBIT-71",
                    source_ref="user:global-preference",
                )

                hits_a = workspace.memory.search(
                    "ORBIT-71",
                    project_id=project_a["id"],
                    session_id=session_a,
                    limit=10,
                )
                ids_a = {item["memory_id"] for item in hits_a}
                self.assertIn(memory_a["memory_id"], ids_a)
                self.assertNotIn(memory_b["memory_id"], ids_a)
                self.assertIn(global_memory["memory_id"], ids_a)
                self.assertEqual(memory_a["scope_type"], "project")
                self.assertEqual(memory_a["fact_level"], "context")

    def test_knowledge_read_expands_scoped_source_to_l2_with_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                project = workspace.repository.create_project({"name": "A"})
                other = workspace.repository.create_project({"name": "B"})
                doc = workspace.repository.import_document(
                    {
                        "title": "Guide",
                        "content": "prefix " + ("evidence " * 1200) + "suffix",
                        "project_id": project["id"],
                    }
                )
                foreign = workspace.repository.import_document(
                    {
                        "title": "Foreign",
                        "content": "secret",
                        "project_id": other["id"],
                    }
                )
                sid = workspace.repository.create_session(project_id=project["id"])["id"]
                rid = workspace.repository.create_turn(
                    sid, "read evidence", "req-knowledge-l2"
                )["run_id"]
                turn = workspace.repository.turn(rid)

                result = workspace.execution._read_knowledge(
                    turn,
                    {"document_id": doc["id"], "offset": 7, "max_chars": 120},
                )
                self.assertEqual(result["resolution"], "L2")
                self.assertEqual(result["digest"], doc["digest"])
                self.assertTrue(result["source_ref"].startswith(f"doc:{doc['id']}@"))
                self.assertTrue(result["has_more"])
                self.assertGreater(result["next_offset"], 7)

                with self.assertRaises(PermissionError):
                    workspace.execution._read_knowledge(
                        turn,
                        {"document_id": foreign["id"]},
                    )


if __name__ == "__main__":
    unittest.main()
