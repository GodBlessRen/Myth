"""回归边界：跨会话/重启长期进度。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "max_output_tokens": 512,
    "num_ctx": 8192,
    "temperature": 0.0,
}


# 跨会话/重启长期进度的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class GoalWorkLoopTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.workspace.repository.save_settings(SETTINGS)

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 回归断言：长期进度真实重开后进入另一 Session 的冻结准入快照。
    def test_goal_work_state_survives_restart_and_cross_session_admission(self):
        goal = self.workspace.personal.create_goal(
            "持续推进 Myth",
            "每次从上一个 durable checkpoint 继续。",
        )
        self.assertEqual(goal["work"]["current_state"], "READY")
        first_sid = self.workspace.repository.create_session()["id"]
        first = self.workspace.repository.create_turn(
            first_sid,
            "先完成第一步",
            "goal-first-run",
            goal_id=goal["goal_id"],
            goal_context=goal,
        )
        self.workspace.personal.bind_run(goal["goal_id"], first["run_id"])
        self.workspace.control.ensure(first["run_id"])
        self.workspace.run(
            first["run_id"],
            ChatProvider([decision(claim="第一步已经完成，下一步检查真实任务基线。")]),
        )
        after = self.workspace.personal.goal_view(goal["goal_id"])
        self.assertEqual(after["work"]["last_run_id"], first["run_id"])
        self.assertEqual(after["work"]["current_state"], "READY")
        self.assertIn("第一步已经完成", after["work"]["progress_note"])

        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        current = self.workspace.personal.goal_view(goal["goal_id"])
        second_sid = self.workspace.repository.create_session()["id"]
        second = self.workspace.repository.create_turn(
            second_sid,
            "继续这个 Goal",
            "goal-second-session",
            goal_id=goal["goal_id"],
            goal_context=current,
        )
        snapshot = self.workspace.repository.turn(second["run_id"])["snapshot"]
        self.assertEqual(snapshot["goal"]["goal_id"], goal["goal_id"])
        self.assertEqual(
            snapshot["goal"]["work"]["revision"], current["work"]["revision"]
        )
        self.assertIn("第一步已经完成", snapshot["goal"]["work"]["progress_note"])

    # 回归断言：等待明确答案时长期进度保存 waiting_for，不伪造目标完成。
    def test_waiting_user_updates_goal_checkpoint(self):
        goal = self.workspace.personal.create_goal("需要用户决定")
        sid = self.workspace.repository.create_session()["id"]
        turn = self.workspace.repository.create_turn(
            sid,
            "推进直到需要我决定",
            "goal-wait",
            goal_id=goal["goal_id"],
            goal_context=goal,
        )
        self.workspace.personal.bind_run(goal["goal_id"], turn["run_id"])
        self.workspace.control.ensure(turn["run_id"])
        provider = ChatProvider([decision(kind="ask_user", question="请选择 A 或 B")])
        self.workspace.run(turn["run_id"], provider)
        work = self.workspace.personal.work_state(goal["goal_id"])
        self.assertEqual(work["current_state"], "WAITING")
        self.assertEqual(work["last_run_id"], turn["run_id"])
        self.assertIn("A 或 B", work["waiting_for"])

    # 回归断言：进度 revision 单调递增，旧记录不能冒充最新状态。
    def test_goal_checkpoint_revision_is_monotonic(self):
        goal = self.workspace.personal.create_goal("revision")
        r1 = goal["work"]["revision"]
        one = self.workspace.personal.update_work_state(
            goal["goal_id"], progress_note="one", next_action="two"
        )
        two = self.workspace.personal.update_work_state(
            goal["goal_id"], progress_note="two", next_action="three"
        )
        self.assertEqual(one["work"]["revision"], r1 + 1)
        self.assertEqual(two["work"]["revision"], r1 + 2)

    # 回归断言：第三栏 Goal/预算/恢复/上下文等事实区域持续存在。
    def test_webui_keeps_runtime_observability_surfaces(self):
        webui = Path(__file__).resolve().parents[1] / "src" / "myth" / "webui"
        html = (webui / "index.html").read_text(encoding="utf-8")
        inspector = (webui / "inspector.js").read_text(encoding="utf-8")
        for identity in (
            "runtimeInspector",
            "executionSpine",
            "inspectorTrajectory",
            "inspectorTokens",
            "inspectorContext",
            "inspectorTools",
            "inspectorBudgets",
            "inspectorGoal",
        ):
            self.assertIn(identity, html)
        for fn in (
            "renderInspectorGoal",
            "renderExecutionSpine",
            "renderInspectorTrajectory",
            "renderInspectorTokens",
            "renderInspectorContext",
            "renderInspectorTools",
            "renderInspectorBudgets",
        ):
            self.assertIn(fn, inspector)


if __name__ == "__main__":
    unittest.main()
