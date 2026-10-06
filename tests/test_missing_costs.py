"""缺测不是零成本：覆盖 Web 投影、SOTA 比较和冻结环境的真实目录边界。"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


class MissingCostsTests(unittest.TestCase):
    """公开收据不足时保留未知；只证明本地事实投影，不推断远端模型可靠性。"""

    def test_web_partial_or_invalid_usage_does_not_become_a_total(self):
        """部分收据或 bool/文本/负数不能成为完整 Token、缓存或耗时聚合。"""
        for value in ({}, {"input_tokens": True, "output_tokens": "2", "provider_wall_ms": -1}):
            with self.subTest(value=value):
                summary = ConversationWebService._model_usage_summary([
                    {"usage": {"input_tokens": 10, "output_tokens": 2, "cached_input_tokens": 5, "provider_wall_ms": 100}},
                    {"usage": value},
                ])
                for field in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_hit_rate", "provider_wall_ms"):
                    self.assertIsNone(summary[field], field)

    def test_web_duplicate_attempt_and_real_zero_keep_their_meaning(self):
        """同一收据只计一次；实测 0 与未报告可区分，错误首 token 不制造 TTFT。"""
        invocation = {"model_attempt_id": "one", "usage": {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0, "provider_wall_ms": 0, "time_to_first_token_ms": -1}}
        summary = ConversationWebService._model_usage_summary([invocation, invocation])
        self.assertEqual(summary["model_calls"], 1)
        self.assertEqual(summary["input_tokens"], 0)
        self.assertEqual(summary["cached_input_tokens"], 0)
        self.assertIsNone(summary["first_token_ms"])

    def test_sota_unknown_token_measurement_cannot_beat_known_cost(self):
        """真实 SQLite 用量缺测，账户已结算值不能替代实测并产生虚假的成本赢家。"""
        with tempfile.TemporaryDirectory() as task_root, MythRuntime(Path(task_root)) as runtime:
            workspace = Workspace(runtime)
            repo = workspace.repository
            repo.save_settings({"provider": "ollama", "model": "test"})
            sid = repo.create_session()["id"]
            rid = repo.create_turn(sid, "same task", "cost") ["run_id"]
            workspace.run(rid, ChatProvider([decision(claim="done")]))
            with runtime.store.tx() as db:
                row = db.execute("SELECT usage_json FROM model_invocations WHERE run_id=?", (rid,)).fetchone()
                usage = json.loads(row[0])
                usage.pop("input_tokens", None)
                usage.pop("provider_wall_ms", None)
                db.execute("UPDATE model_invocations SET usage_json=? WHERE run_id=?", (json.dumps(usage), rid))
            metrics = workspace.sota_route.metrics(rid)
            self.assertIsNone(metrics["input_tokens"])
            self.assertIsNone(metrics["total_tokens"])
            self.assertIsNone(metrics["work_ms"])
            self.assertFalse(workspace.sota_route._beats({**metrics, "model_calls": 0}, {**metrics, "total_tokens": 100, "model_calls": 1}))

    def test_environment_does_not_traverse_or_hash_work_directory(self):
        """私有学习/过程目录在遍历前剪枝，不能增加扫描成本或改变项目比赛身份。"""
        with tempfile.TemporaryDirectory() as task_root, MythRuntime(Path(task_root) / "runtime") as runtime:
            project = Path(task_root) / "project"
            project.mkdir()
            (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            work = project / ".work" / "deep"
            work.mkdir(parents=True)
            evidence = work / "private.md"
            evidence.write_text("private process", encoding="utf-8")
            ledger = Workspace(runtime).sota_route
            scanned = []
            original = os.scandir

            def scan(path):
                """记录实际扫描目录，保留真实 scandir 返回值与异常。"""
                scanned.append(str(path))
                return original(path)

            with patch("os.scandir", side_effect=scan):
                before = ledger.freeze_environment({"project": {"root": str(project)}})
            self.assertFalse(any(".work" in path for path in scanned), scanned)
            self.assertEqual(before["files"], 1)
            evidence.write_text("changed private process", encoding="utf-8")
            self.assertEqual(ledger.freeze_environment({"project": {"root": str(project)}}), before)


if __name__ == "__main__":
    unittest.main()
