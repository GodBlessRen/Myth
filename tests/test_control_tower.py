"""回归边界：持久控制、记忆与受限项目工具。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.platform.control import ControlCommand


# 持久控制、记忆与受限项目工具的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ControlTowerTests(unittest.TestCase):
    # 在明确临时根装配真实仓储和可控供应商；不读取用户项目。
    def _workspace(self, root: Path):
        runtime = MythRuntime(root)
        workspace = Workspace(runtime)
        workspace.repository.save_settings(
            {
                "provider": "ollama",
                "model": "demo-model",
                "ollama_url": "http://127.0.0.1:11434",
                "max_steps": 6,
                "max_output_tokens": 512,
                "thinking": False,
            }
        )
        return runtime, workspace

    # 回归断言：控制修订持久保存，正常安全点消费；旧收据不能清新命令。
    def test_control_persists_pause_resume_switches_compact_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, workspace = self._workspace(Path(tmp))
            try:
                session = workspace.repository.create_session("control")
                turn = workspace.repository.create_turn(
                    session["id"], "hello", "req-control"
                )
                rid = turn["run_id"]
                workspace.control.ensure(rid, turn["settings"])

                paused = workspace.control.command(rid, ControlCommand.PAUSE)
                self.assertTrue(paused["paused"])
                self.assertEqual(workspace.repository.turn(rid)["status"], "PAUSED")
                run_state = runtime.store.db.execute(
                    "SELECT state FROM runs WHERE run_id=?", (rid,)
                ).fetchone()[0]
                self.assertEqual(run_state, "PAUSED")

                switched = workspace.control.command(
                    rid, ControlCommand.SWITCH_MODEL, "model-b"
                )
                self.assertEqual(switched["model"], "model-b")
                self.assertEqual(
                    workspace.repository.turn(rid)["settings"]["model"], "model-b"
                )

                thinking = workspace.control.command(
                    rid, ControlCommand.SWITCH_THINKING, "high"
                )
                self.assertEqual(thinking["thinking"], "high")
                self.assertEqual(
                    workspace.repository.turn(rid)["settings"]["thinking"], "high"
                )

                steered = workspace.control.command(
                    rid, ControlCommand.STEER, "compare before editing"
                )
                self.assertEqual(steered["steering_note"], "compare before editing")

                resumed = workspace.control.command(rid, ControlCommand.RESUME)
                self.assertFalse(resumed["paused"])
                self.assertEqual(workspace.repository.turn(rid)["status"], "RUNNING")

                compact = workspace.control.command(rid, ControlCommand.COMPACT)
                self.assertTrue(compact["compact_requested"])
                workspace.control.consume_compaction(rid)
                self.assertFalse(workspace.control.view(rid)["compact_requested"])

                stopped = workspace.control.command(rid, ControlCommand.STOP)
                self.assertTrue(stopped["stopped"])
                self.assertEqual(workspace.repository.turn(rid)["status"], "CANCELLED")
                with self.assertRaises(ValueError):
                    workspace.control.command(rid, ControlCommand.RESUME)
            finally:
                runtime.close()

    # 回归断言：真实仓储记忆可重开/更新/词面检索/撤下，来源保持可解释。
    def test_memory_is_persistent_revisioned_searchable_and_revocable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, workspace = self._workspace(Path(tmp))
            try:
                first = workspace.memory.remember(
                    kind="semantic",
                    text="Myth uses a durable Ticket before external execution.",
                    source_ref="user:runtime-rule",
                )
                second = workspace.memory.remember(
                    kind="semantic",
                    text="Myth keeps UNKNOWN outcomes explicit.",
                    source_ref="user:runtime-rule",
                )
                self.assertEqual(second["memory_id"], first["memory_id"])
                self.assertEqual(second["revision"], 2)
                hits = workspace.memory.search("UNKNOWN outcomes")
                self.assertEqual(hits[0]["memory_id"], first["memory_id"])
                revoked = workspace.memory.revoke(first["memory_id"])
                self.assertEqual(revoked["active"], 0)
                self.assertEqual(workspace.memory.search("UNKNOWN outcomes"), [])

                episode = workspace.memory.record_episode(
                    "run_demo", "Question", "Answer"
                )
                self.assertEqual(episode["kind"], "episodic")
                self.assertTrue(episode["source_ref"].startswith("run:"))
            finally:
                runtime.close()

    # 回归断言：搜索、Diff 和 Git 使用受限根/固定只读命令，原项目不修改。
    def test_search_diff_and_git_capabilities_are_read_only_and_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (project / "app.py").write_text(
                "print('hello')\n# durable runtime\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "init"], cwd=project, check=True, capture_output=True, text=True
            )

            runtime, workspace = self._workspace(root / "runtime")
            try:
                turn = {
                    "snapshot": {"project": {"root": str(project)}},
                    "session_id": "session_test",
                }
                search = workspace.execution._search_project(
                    turn, {"query": "durable", "limit": 5}
                )
                self.assertEqual(search["matches"][0]["path"], "app.py")

                diff = workspace.execution._diff_preview(
                    turn,
                    {
                        "path": "app.py",
                        "content": "print('hello')\n# verified runtime\n",
                    },
                )
                self.assertIn("-# durable runtime", diff["diff"])
                self.assertIn("+# verified runtime", diff["diff"])
                self.assertEqual(
                    (project / "app.py").read_text(encoding="utf-8"),
                    "print('hello')\n# durable runtime\n",
                )

                status = workspace.execution._git(turn, "git.status", {})
                self.assertIn("app.py", status["output"])
                git_diff = workspace.execution._git(turn, "git.diff", {})
                self.assertEqual(git_diff["output"], "")

                with self.assertRaises(PermissionError):
                    workspace.execution._search_project(
                        turn, {"query": "x", "path": "../", "limit": 5}
                    )
            finally:
                runtime.close()

    # 回归断言：新增已实现工具与目录一致，不仅注册空合同。
    def test_new_coding_capabilities_are_registry_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, workspace = self._workspace(Path(tmp))
            try:
                executable = set(workspace.kernel.capabilities.executable_ids())
                self.assertTrue(
                    {
                        "project.search",
                        "diff.preview",
                        "git.status",
                        "git.diff",
                        "test.run",
                    }
                    <= executable
                )
                # 任意 shell 仍未获得执行资格；test.run 只接受显式受信的固定 profile。
                self.assertNotIn("shell.exec", executable)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
