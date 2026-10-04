"""v0.24 交付闭环：终态补偿、验收、工作项、人工关注与受限测试 profile。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


# 以独立 SQLite 和受信测试项目核对收尾、验收与人工关注；不调用真实模型。
class DeliveryWorkflowTests(unittest.TestCase):
    # 建立隔离根、真实仓储与 Session，确保用例不共享持久状态。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})
        self.sid = self.repo.create_session()["id"]

    # 关闭数据库后清理临时目录，避免 Windows 持有文件句柄。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 回答结束会补齐收尾义务；验收仍未验证，Goal 不再假装持续执行。
    def test_completion_creates_finalization_and_unverified_acceptance(self):
        goal = self.workspace.personal.create_goal("Ship one checked deliverable")
        turn = self.repo.create_turn(
            self.sid,
            "Prepare the deliverable",
            "delivery-normal",
            goal_id=goal["goal_id"],
            goal_context=goal,
        )
        self.workspace.control.ensure(turn["run_id"])
        self.workspace.run(turn["run_id"], ChatProvider([decision(claim="Draft ready")]))
        view = self.workspace.delivery.run_view(turn["run_id"])
        self.assertEqual(self.repo.turn(turn["run_id"])["status"], "COMPLETED")
        self.assertEqual(view["finalization"]["state"], "DONE")
        self.assertEqual(view["acceptance"]["state"], "UNVERIFIED")
        self.assertEqual(view["work_items"][0]["status"], "DONE")
        self.assertNotEqual(
            self.workspace.personal.work_state(goal["goal_id"])["current_state"],
            "IN_PROGRESS",
        )

    # 在回答已提交、Memory 尚未写入时真实退出；重开补偿，不重放模型。
    def test_hard_exit_after_answer_commit_is_reconciled_without_model_replay(self):
        child_root = self.root / "terminal-crash"
        source_root = Path(__file__).resolve().parents[1]
        script = r"""
import json, os, sys
from pathlib import Path
sys.path[:0] = [sys.argv[2], sys.argv[3]]
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision
root = Path(sys.argv[1])
with MythRuntime(root) as runtime:
    w = Workspace(runtime)
    w.repository.save_settings({"provider":"ollama","model":"test"})
    goal = w.personal.create_goal("Crash goal")
    sid = w.repository.create_session()["id"]
    turn = w.repository.create_turn(
        sid, "Finish exactly once", "terminal-crash",
        goal_id=goal["goal_id"], goal_context=goal
    )
    w.control.ensure(turn["run_id"])
    (root/"ids.json").write_text(
        json.dumps({"run_id":turn["run_id"],"goal_id":goal["goal_id"]})
    )
    w.memory.record_episode = lambda *a, **k: os._exit(73)
    w.run(turn["run_id"], ChatProvider([decision(claim="Committed answer")]))
"""
        child = subprocess.run(
            [
                sys.executable, "-c", script, str(child_root),
                str(source_root / "src"), str(source_root / "tests"),
            ],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(child.returncode, 73, child.stderr)
        ids = json.loads((child_root / "ids.json").read_text())
        with MythRuntime(child_root) as runtime:
            workspace = Workspace(runtime)
            self.assertEqual(workspace.repository.turn(ids["run_id"])["status"], "COMPLETED")
            view = workspace.delivery.run_view(ids["run_id"])
            self.assertEqual(view["finalization"]["state"], "DONE")
            self.assertEqual(view["acceptance"]["state"], "UNVERIFIED")
            self.assertNotEqual(
                workspace.personal.work_state(ids["goal_id"])["current_state"],
                "IN_PROGRESS",
            )

    # 验收绑定当前对象摘要，人工审查耗时独立计量；旧摘要必须拒绝。
    def test_acceptance_binds_subject_and_human_attention(self):
        rid = self.repo.create_turn(self.sid, "Review me", "acceptance")["run_id"]
        self.workspace.run(rid, ChatProvider([decision(claim="Answer")]))
        current = self.workspace.delivery.acceptance(rid)
        passed = self.workspace.delivery.set_acceptance(
            rid,
            state="PASSED",
            checker_id="human/review",
            subject_digest=current["subject_digest"],
            evidence=["manual:review"],
            note="Reviewed against requested output.",
        )
        self.assertEqual(passed["state"], "PASSED")
        self.workspace.delivery.record_attention(
            rid, kind="review", seconds=90, note="Read answer and evidence."
        )
        self.assertEqual(self.workspace.delivery.run_view(rid)["attention"]["seconds"], 90)
        self.assertEqual(self.workspace.delivery.metrics()["acceptance"]["PASSED"], 1)
        with self.assertRaises(ValueError):
            self.workspace.delivery.set_acceptance(
                rid, state="PASSED", checker_id="stale", subject_digest="0" * 64
            )

    # 工作计划修订严格前进，依赖引用按持久 ordinal 保存。
    def test_work_plan_revision_is_monotonic(self):
        rid = self.repo.create_turn(self.sid, "Multi-stage work", "plan")["run_id"]
        self.workspace.delivery.ensure_root_work_item(self.repo.turn(rid))
        items = self.workspace.delivery.plan_work_items(
            rid,
            [
                {"title": "Read evidence", "acceptance": {"requires": ["source refs"]}},
                {"title": "Prepare candidate", "dependencies": [2]},
                {"title": "Verify candidate", "dependencies": [3]},
            ],
        )
        self.assertEqual([item["ordinal"] for item in items], [1, 2, 3, 4])
        self.assertEqual(items[-1]["plan_revision"], 2)
        with self.assertRaises(ValueError):
            self.workspace.delivery.plan_work_items(
                rid, [{"title": "old plan"}], plan_revision=2
            )

    # 显式受信 profile 才启动固定 unittest；测试 PASS 不自动等于交付验收。
    def test_trusted_python_unittest_profile_executes_via_receipt(self):
        project_root = self.root / "fixture-project"
        tests = project_root / "tests"
        tests.mkdir(parents=True)
        (tests / "test_ok.py").write_text(
            "import unittest\n"
            "class Ok(unittest.TestCase):\n"
            "    def test_ok(self): self.assertEqual(2+3, 5)\n",
            encoding="utf-8",
        )
        project = self.repo.create_project({"name": "fixture", "root": str(project_root)})
        sid = self.repo.create_session(project_id=project["id"])["id"]
        with self.assertRaises(ValueError):
            self.workspace.verification.create(
                project["id"], {"name": "implicit trust", "trusted_project": False}
            )
        profile = self.workspace.verification.create(
            project["id"],
            {
                "name": "fixture tests",
                "trusted_project": True,
                "test_dir": "tests",
                "timeout_seconds": 20,
            },
        )
        rid = self.repo.create_turn(sid, "Run admitted tests", "verify-profile")["run_id"]
        self.workspace.run(
            rid,
            ChatProvider(
                [
                    decision("tool_call", "test.run", {"profile_id": profile["profile_id"]}),
                    decision(claim="Tests executed; inspect the receipt."),
                ]
            ),
        )
        operation = self.repo.operations(rid)[0]
        self.assertEqual(operation["capability"], "test.run")
        self.assertEqual(operation["result"]["status"], "PASSED")
        self.assertTrue(operation["result"]["evidence_ref"].startswith("test:"))
        self.assertEqual(self.workspace.delivery.acceptance(rid)["state"], "UNVERIFIED")

    # Web 展示持久 Delivery 事实，普通回答仍显示 UNVERIFIED。
    def test_web_projection_exposes_delivery_metrics(self):
        rid = self.repo.create_turn(self.sid, "Visible delivery", "web-delivery")["run_id"]
        self.workspace.run(rid, ChatProvider([decision(claim="Visible")]))
        service = ConversationWebService(self.root)
        session = service.session(self.sid)
        self.assertEqual(
            session["turns"][-1]["delivery"]["acceptance"]["state"], "UNVERIFIED"
        )
        self.assertGreaterEqual(service.delivery_metrics()["admitted_deliveries"], 1)


if __name__ == "__main__":
    unittest.main()
