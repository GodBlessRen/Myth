"""回归边界：固定知识路由和历史评测执行。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.conversation import conversation_request
from myth.evaluation_runner import FoundationEvalRunner
from myth.platform import Maturity, MythComponents
from myth.runtime import MythRuntime
from myth.workspace import Workspace


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "ollama_url": "http://127.0.0.1:11434",
    "max_steps": 6,
    "max_output_tokens": 512,
    "thinking": False,
}


# 固定知识路由和历史评测执行的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class EvalRoutingTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings(SETTINGS)

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 回归断言：明确知识请求固定召回路由及 L1，未来策略变化不倒写快照。
    def test_explicit_local_knowledge_request_freezes_local_retrieval_and_l1(self):
        doc = self.repo.import_document(
            {
                "title": "交付资料",
                "content": "Myth 的交付代号是 SILVER-92，发布时间是周五。",
            }
        )
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(
            sid,
            "根据资料，SILVER-92 的发布时间是什么？",
            "v013-local-retrieval",
        )["run_id"]
        turn = self.repo.turn(rid)
        snapshot = turn["snapshot"]

        self.assertEqual(snapshot["intent_pick"]["route"], "local_retrieval")
        self.assertEqual(snapshot["information_resolution"]["resolution"], "L1")
        self.assertGreaterEqual(snapshot["retrieval_report"]["scanned"], 1)
        self.assertFalse(snapshot["retrieval_report"]["truncated_before_ranking"])
        self.assertEqual(snapshot["knowledge"][0]["document_id"], doc["id"])
        self.assertEqual(snapshot["knowledge"][0]["resolution"], "L1")
        self.assertEqual(
            snapshot["knowledge"][0]["source_ref"],
            f"doc:{doc['id']}@{doc['digest']}",
        )

        request = conversation_request(
            turn["settings"],
            snapshot,
            snapshot["messages"],
            [],
            {},
        )
        self.assertEqual(request.context_report["intent_route"], "local_retrieval")
        self.assertEqual(request.context_report["information_resolution"], "L1")
        self.assertEqual(
            request.context_report["retrieval_report"]["scanned"],
            snapshot["retrieval_report"]["scanned"],
        )

    # 回归断言：显式附件优先进入 L2 表示，词面策略不能静默丢弃。
    def test_explicit_attachment_is_never_dropped_and_uses_l2(self):
        docs = [
            self.repo.import_document(
                {
                    "title": f"附件 {i}",
                    "content": f"附件 {i} 的唯一值是 ATTACH-{i}。" + (" detail" * 400),
                }
            )
            for i in range(4)
        ]
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(
            sid,
            "请详细阅读这些附件原文并给出处。",
            "v013-pinned-l2",
            document_ids=[item["id"] for item in docs],
        )["run_id"]
        snapshot = self.repo.turn(rid)["snapshot"]

        self.assertEqual(snapshot["intent_pick"]["route"], "local_retrieval")
        self.assertEqual(snapshot["information_resolution"]["resolution"], "L2")
        self.assertTrue(
            {item["id"] for item in docs}
            <= {item["document_id"] for item in snapshot["knowledge"]}
        )
        for item in snapshot["knowledge"]:
            if item["document_id"] in {doc["id"] for doc in docs}:
                self.assertEqual(item["resolution"], "L2")
                self.assertIn("@", item["source_ref"])

    # 回归断言：没有本地证据时不冒充知识已回答，保留 Agent 路径。
    def test_no_local_evidence_stays_agent_with_l0(self):
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(
            sid,
            "帮我分析一个新的产品方案。",
            "v013-agent-fallback",
        )["run_id"]
        snapshot = self.repo.turn(rid)["snapshot"]
        self.assertEqual(snapshot["intent_pick"]["route"], "agent")
        self.assertEqual(snapshot["information_resolution"]["resolution"], "L0")
        self.assertEqual(snapshot["knowledge"], [])

    # 回归断言：固定探针实际执行并据完整覆盖给资格，不只加载题表。
    def test_quick_eval_runner_executes_fixed_cases_and_release_gate(self):
        suite = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "archive"
            / "foundation-v2.json"
        )
        result = FoundationEvalRunner.from_path(suite).run(
            [
                "intent-arithmetic-local",
                "intent-ambiguous-fallback",
            ]
        )
        self.assertEqual(result["report"]["pass_count"], 2)
        self.assertEqual(result["report"]["fail_count"], 0)
        self.assertTrue(result["release_gate"]["passed"])
        self.assertTrue(
            all(item["verdict"] == "PASS" for item in result["observations"])
        )

    # 回归断言：历史固定集每题均有明确 Runner handler；不支持题保持可见。
    def test_foundation_suite_has_executable_handler_for_every_fixed_case(self):
        suite = (
            Path(__file__).resolve().parents[1]
            / "evals"
            / "archive"
            / "foundation-v2.json"
        )
        runner = FoundationEvalRunner.from_path(suite)
        self.assertEqual(runner.suite.version, 2)
        self.assertEqual(len(runner.suite.cases), 11)
        for case in runner.suite.cases:
            self.assertTrue(
                hasattr(runner, f"_case_{case.case_id.replace('-','_')}"),
                case.case_id,
            )

    # 回归断言：已装配评测与尚未校准增益的成熟度分别报告。
    def test_evaluation_domain_is_usable_but_gain_remains_unpromoted(self):
        snapshot = MythComponents.default().snapshot()
        domains = {item["id"]: item for item in snapshot["domains"]}
        self.assertEqual(domains["evaluation"]["maturity"], Maturity.USABLE.value)
        strategies = {item["id"]: item for item in snapshot["strategies"]}
        self.assertEqual(strategies["information_resolution"]["maturity"], "connected")
        self.assertEqual(strategies["information_gain"]["maturity"], "connected")


if __name__ == "__main__":
    unittest.main()
