from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.core import GoalState
from myth.runtime import MythRuntime
from myth.workspace import Workspace


class PersonalAgentFoundationTests(unittest.TestCase):
    def test_goal_trigger_and_personal_state_are_explicit_and_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with MythRuntime(root) as runtime:
                workspace=Workspace(runtime)
                goal=workspace.personal.create_goal(
                    "Find suitable roles",
                    "Long-lived job-search intent that may own many future Runs.",
                )
                trigger=workspace.personal.add_trigger(
                    goal["goal_id"],
                    "schedule",
                    {"cron":"0 8 * * *"},
                )
                workspace.repository.save_settings({
                    "provider":"ollama",
                    "model":"demo-model",
                    "ollama_url":"http://127.0.0.1:11434",
                    "max_steps":4,
                    "max_output_tokens":256,
                    "thinking":False,
                })
                session=workspace.repository.create_session("goal work")
                turn=workspace.repository.create_turn(session["id"],"first run","req-goal")
                workspace.personal.bind_run(goal["goal_id"],turn["run_id"])
                workspace.personal.set_state(
                    "permission.email_send",
                    {"allowed":False,"approval_required":True},
                )

                self.assertEqual(goal["state"],GoalState.ACTIVE.value)
                self.assertEqual(trigger["goal_id"],goal["goal_id"])
                self.assertEqual(trigger["kind"],"schedule")
                self.assertFalse(workspace.personal.state()["permission.email_send"]["allowed"])
                self.assertEqual(workspace.personal.runs(goal["goal_id"])[0]["run_id"],turn["run_id"])

            with MythRuntime(root) as runtime:
                workspace=Workspace(runtime)
                goals=workspace.personal.goals()
                self.assertEqual(goals[0]["title"],"Find suitable roles")
                self.assertEqual(workspace.personal.triggers(goals[0]["goal_id"])[0]["kind"],"schedule")
                self.assertTrue(workspace.personal.state()["permission.email_send"]["approval_required"])

    def test_goal_state_is_not_memory_and_trigger_does_not_auto_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MythRuntime(Path(tmp)) as runtime:
                workspace=Workspace(runtime)
                goal=workspace.personal.create_goal("Monitor a future condition")
                paused=workspace.personal.set_goal_state(goal["goal_id"],"PAUSED")
                workspace.personal.add_trigger(goal["goal_id"],"event",{"topic":"example"})

                self.assertEqual(paused["state"],"PAUSED")
                self.assertEqual(workspace.memory.list(), [])
                self.assertEqual(runtime.store.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
