"""回归边界：Control 竞争、Goal 准入和作用域。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

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


# Control 竞争、Goal 准入和作用域的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class RuntimeClosureTests(unittest.TestCase):
    # 回归断言：真实两连接更新 Control 时 revision 无丢失，命令和投影同事务。
    def test_control_revision_allocation_is_atomic_across_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                sid = workspace.repository.create_session("control")["id"]
                turn = workspace.repository.create_turn(
                    sid, "hello", "req-control-race"
                )
                rid = turn["run_id"]
                workspace.control.ensure(rid)

            barrier = threading.Barrier(2)
            revisions: list[int] = []
            errors: list[BaseException] = []
            lock = threading.Lock()

            # Control 竞争、Goal 准入和作用域的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
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
            # 每条命令在自己的事务内生成响应，调用者必须拿到自己提交的版本。
            self.assertEqual(sorted(revisions), [2, 3])
            with MythRuntime(root) as runtime:
                view = Workspace(runtime).control.view(rid)
                history = view["commands"]
                self.assertEqual(view["revision"], 3)
                self.assertEqual([item["revision"] for item in history], [2, 3])

    # 回归断言：长期 Goal 身份有效才允许整项 Turn 准入。
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

    # 回归断言：经历保留项目/Session 范围，共享记忆可见但不泄漏其他项目经历。
    def test_episodic_memory_is_scoped_and_global_memory_remains_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                project_a = workspace.repository.create_project({"name": "A"})
                project_b = workspace.repository.create_project({"name": "B"})
                session_a = workspace.repository.create_session(
                    project_id=project_a["id"]
                )["id"]
                session_b = workspace.repository.create_session(
                    project_id=project_b["id"]
                )["id"]
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

    # 回归断言：展开知识核对作用域和摘要；不能以 document id 绕开范围。
    def test_knowledge_resolve_expands_scoped_source_to_l2_with_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                project = workspace.repository.create_project({"name": "A"})
                other = workspace.repository.create_project({"name": "B"})
                doc = workspace.repository.knowledge.import_document(
                    {
                        "title": "Guide",
                        "content": "prefix " + ("evidence " * 1200) + "suffix",
                        "project_id": project["id"],
                    }
                )
                foreign = workspace.repository.knowledge.import_document(
                    {
                        "title": "Foreign",
                        "content": "secret",
                        "project_id": other["id"],
                    }
                )
                sid = workspace.repository.create_session(project_id=project["id"])[
                    "id"
                ]
                rid = workspace.repository.create_turn(
                    sid, "read evidence", "req-knowledge-l2"
                )["run_id"]
                turn = workspace.repository.turn(rid)

                result = workspace.execution._resolve_knowledge(
                    turn,
                    {"document_id": doc["id"], "resolution": "L2", "cursor": 7, "limit": 120},
                )
                self.assertEqual(result["resolution"], "L2")
                self.assertEqual(result["digest"], doc["digest"])
                self.assertTrue(result["source_ref"].startswith(f"doc:{doc['id']}@"))
                self.assertTrue(result["has_more"])
                self.assertGreater(result["next_cursor"], 7)

                # L1 必须按分片游标前进，分页期间 digest 不变，最终页明确结束。
                chunks, cursor = [], 0
                while True:
                    page = workspace.execution._resolve_knowledge(
                        turn, {"document_id": doc["id"], "resolution": "L1", "cursor": cursor, "limit": 1}
                    )
                    self.assertEqual(page["digest"], doc["digest"])
                    chunks.extend(item["chunk_index"] for item in page["chunks"])
                    if not page["has_more"]:
                        self.assertIsNone(page["next_cursor"])
                        break
                    self.assertGreater(page["next_cursor"], cursor)
                    cursor = page["next_cursor"]
                self.assertGreater(len(chunks), 1)
                self.assertEqual(chunks, list(range(len(chunks))))
                for resolution in ("L0", "L1"):
                    for args in ({"cursor": True}, {"cursor": -1}, {"limit": 0}, {"limit": 21}, {"limit": "2"}):
                        with self.subTest(resolution=resolution, args=args), self.assertRaises(ValueError):
                            workspace.execution._resolve_knowledge(
                                turn, {"document_id": doc["id"], "resolution": resolution, **args}
                            )

                with self.assertRaises(PermissionError):
                    workspace.execution._resolve_knowledge(
                        turn,
                        {"document_id": foreign["id"]},
                    )

    # 回归断言：严格算术规则路径可零模型调用结束，仍留路由来源事实。
    def test_strict_arithmetic_intent_finishes_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.save_settings(SETTINGS)
                sid = workspace.repository.create_session("math")["id"]
                rid = workspace.repository.create_turn(
                    sid, "计算 2+3*4", "req-local-math"
                )["run_id"]

                # Control 竞争、Goal 准入和作用域的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
                class NeverCalled:
                    provider_id = "ollama"
                    calls = 0

                    # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
                    def invoke(self, request):
                        self.calls += 1
                        raise AssertionError(
                            "deterministic fast path must not invoke the model"
                        )

                provider = NeverCalled()
                workspace.run(rid, provider)
                turn = workspace.repository.turn(rid)
                self.assertEqual(turn["status"], "COMPLETED")
                self.assertEqual(provider.calls, 0)
                self.assertEqual(
                    workspace.repository.session(sid)["messages"][-1]["content"],
                    "14",
                )
                accounts = {item["meter"]: item for item in turn["budgets"]}
                self.assertEqual(accounts["model_calls"]["settled"], 0)


if __name__ == "__main__":
    unittest.main()
