"""SOTA Route 回归：只从已验收成功 Run 学习同条件下更省的可观察路径。
固定夹具只证明账本/比较/提示边界，不代表真实模型一定复现最佳路线。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


# SOTA Route 的固定回归集合；每个测试独占 Runtime，避免历史成功路径串组。
class SotaRouteTests(unittest.TestCase):
    # 建立独立工作区和固定模型设置；模型替身只提供确定路径差异。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})

    # 关闭连接并清理临时目录；不把清理结果算作 SOTA Route 指标。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 创建独立会话中的同任务 Run；独立会话避免历史消息改变冻结环境键。
    def run_task(self, outputs, *, text="完成相同任务", project_id=None, request_id=None):
        sid = self.repo.create_session(project_id=project_id)["id"]
        rid = self.repo.create_turn(
            sid,
            text,
            request_id or f"req-{sid}",
        )["run_id"]
        self.workspace.run(rid, ChatProvider(outputs))
        return rid

    # 显式人工验收当前交付；PASS 才允许进入 SOTA Route 账本。
    def pass_run(self, rid):
        current = self.workspace.delivery.acceptance(rid)
        return self.workspace.delivery.set_acceptance(
            rid,
            state="PASSED",
            checker_id="test/human",
            subject_digest=current["subject_digest"],
            evidence=["test:accepted"],
            note="fixture acceptance",
        )

    # 同质量下更少模型/工具/步骤/Token 的成功路径应成为 Best，旧路径标记为 Beaten。
    def test_passed_run_with_lower_cost_becomes_best(self):
        slow = self.run_task(
            [
                decision("tool_call", "math.calculate", {"expression": "2+3"}),
                decision(claim="完成"),
            ]
        )
        self.pass_run(slow)

        fast = self.run_task([decision(claim="完成")])
        self.pass_run(fast)

        slow_view = self.workspace.sota_route.view(slow)
        fast_view = self.workspace.sota_route.view(fast)
        self.assertEqual(slow_view["status"], "LOSER")
        self.assertEqual(fast_view["status"], "CHAMPION")
        self.assertIn(slow, fast_view["beats"])
        self.assertEqual(fast_view["metrics"]["tool_calls"], 0)
        self.assertLess(
            fast_view["metrics"]["total_tokens"],
            slow_view["metrics"]["total_tokens"],
        )

    # 未验收 Run 只能观察当前成本，不能污染历史最佳成功集合。
    def test_unverified_run_is_not_a_sota_route_candidate(self):
        rid = self.run_task([decision(claim="完成")])
        view = self.workspace.sota_route.view(rid)
        self.assertEqual(view["status"], "WORKING")
        self.assertEqual(view["peer_count"], 0)
        self.assertFalse(view["eligible"])

    # 新 Run 在准入时冻结历史 SOTA Route 提示，模型可参考但不能因此跳过验收/权限。
    def test_future_turn_freezes_sota_route_hint(self):
        winner = self.run_task([decision(claim="完成")])
        self.pass_run(winner)

        sid = self.repo.create_session()["id"]
        turn = self.repo.create_turn(sid, "完成相同任务", "hint-next")
        hint = turn["snapshot"].get("sota_route_hint")
        self.assertIsNotNone(hint)
        self.assertGreaterEqual(hint["passed_runs"], 1)
        self.assertEqual(hint["action_paths"][0], ["reply"])
        self.assertEqual(hint["champion_costs"]["tool_calls"], 0)

    # 项目正文改变后即使任务/模型相同也不能与旧环境比赛，避免错误宣布新的 Best。
    def test_project_state_change_breaks_comparison_group(self):
        project_root = self.root / "project"
        project_root.mkdir()
        source = project_root / "app.py"
        source.write_text("VALUE = 1\n", encoding="utf-8")
        project = self.repo.create_project({"name": "P", "root": str(project_root)})

        first = self.run_task([decision(claim="完成")], project_id=project["id"])
        self.pass_run(first)
        source.write_text("VALUE = 2\n", encoding="utf-8")
        second = self.run_task(
            [decision(claim="完成")],
            project_id=project["id"],
            request_id="changed-project",
        )
        self.pass_run(second)

        self.assertNotEqual(
            self.workspace.sota_route.view(first)["comparison_key"],
            self.workspace.sota_route.view(second)["comparison_key"],
        )
        self.assertEqual(self.workspace.sota_route.view(first)["peer_count"], 1)
        self.assertEqual(self.workspace.sota_route.view(second)["peer_count"], 1)

    # 供应商公开 Reasoning Summary 与 reasoning token 成本进入 SOTA Route；隐藏 CoT 不被伪造。
    def test_reasoning_summary_and_cost_are_kept_for_champion(self):
        rid = self.run_task([decision(claim="完成")])
        row = self.runtime.store.db.execute(
            "SELECT model_attempt_id,response_ref,usage_json FROM model_invocations "
            "WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            (rid,),
        ).fetchone()
        raw = {
            "id": "fixture-reasoning",
            "status": "completed",
            "reasoning_summary": ["先定位最小范围，再直接验证。"],
            "output": [],
            "usage": {},
        }
        response_ref = self.runtime.objects.put(
            __import__("json").dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        usage = __import__("json").loads(row["usage_json"])
        usage["reasoning_tokens"] = 17
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE model_invocations SET response_ref=?,usage_json=? WHERE model_attempt_id=?",
                (
                    response_ref,
                    __import__("json").dumps(usage, ensure_ascii=False, sort_keys=True),
                    row["model_attempt_id"],
                ),
            )
        self.pass_run(rid)
        view = self.workspace.sota_route.view(rid)
        self.assertEqual(view["status"], "CHAMPION")
        self.assertEqual(view["metrics"]["reasoning_tokens"], 17)
        self.assertEqual(
            view["reasoning"]["attempts"][0]["summary"],
            ["先定位最小范围，再直接验证。"],
        )
        hint = self.workspace.sota_route.hint_for_snapshot(
            "完成相同任务",
            self.repo.settings(),
            self.repo.create_turn(
                self.repo.create_session()["id"],
                "完成相同任务",
                "reasoning-hint-probe",
            )["snapshot"],
        )
        self.assertIn("先定位最小范围", hint["reasoning_summaries"][0])

    # 当前路径显著超过历史成功路径时只给 Drift/Replan 提示，不强行停止或伪造失败。
    def test_longer_current_route_is_marked_as_drift(self):
        winner = self.run_task([decision(claim="完成")])
        self.pass_run(winner)

        wandering = self.run_task(
            [
                decision("tool_call", "math.calculate", {"expression": "1+1"}),
                decision("tool_call", "math.calculate", {"expression": "2+2"}),
                decision("tool_call", "math.calculate", {"expression": "3+3"}),
                decision(claim="完成"),
            ],
            request_id="wandering",
        )
        view = self.workspace.sota_route.view(wandering)
        self.assertTrue(view["drift"])
        self.assertIn("tool_calls", view["drift_reasons"])
        self.assertEqual(self.repo.turn(wandering)["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
