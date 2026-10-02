from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.conversation import conversation_request
from myth.evaluation_runner import FoundationEvalRunner
from myth.platform import Maturity, MythComponents
from myth.runtime import MythRuntime
from myth.workspace import Workspace


SETTINGS={
    "provider":"ollama",
    "model":"test",
    "ollama_url":"http://127.0.0.1:11434",
    "max_steps":6,
    "max_output_tokens":512,
    "thinking":False,
}


class EvalRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.runtime=MythRuntime(self.root)
        self.workspace=Workspace(self.runtime)
        self.repo=self.workspace.repository
        self.repo.save_settings(SETTINGS)

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def test_explicit_local_knowledge_request_freezes_local_retrieval_and_l1(self):
        doc=self.repo.import_document({
            "title":"交付资料",
            "content":"Myth 的交付代号是 SILVER-92，发布时间是周五。",
        })
        sid=self.repo.create_session()["id"]
        rid=self.repo.create_turn(
            sid,
            "根据资料，SILVER-92 的发布时间是什么？",
            "v013-local-retrieval",
        )["run_id"]
        turn=self.repo.turn(rid)
        snapshot=turn["snapshot"]

        self.assertEqual(snapshot["intent_pick"]["route"],"local_retrieval")
        self.assertEqual(snapshot["information_resolution"]["resolution"],"L1")
        self.assertGreaterEqual(snapshot["retrieval_report"]["scanned"],1)
        self.assertFalse(snapshot["retrieval_report"]["truncated_before_ranking"])
        self.assertEqual(snapshot["knowledge"][0]["document_id"],doc["id"])
        self.assertEqual(snapshot["knowledge"][0]["resolution"],"L1")
        self.assertEqual(
            snapshot["knowledge"][0]["source_ref"],
            f"doc:{doc['id']}@{doc['digest']}",
        )

        request=conversation_request(
            turn["settings"],
            snapshot,
            snapshot["messages"],
            [],
            {},
        )
        self.assertEqual(request.context_report["intent_route"],"local_retrieval")
        self.assertEqual(request.context_report["information_resolution"],"L1")
        self.assertEqual(
            request.context_report["retrieval_report"]["scanned"],
            snapshot["retrieval_report"]["scanned"],
        )

    def test_explicit_attachment_is_never_dropped_and_uses_l2(self):
        docs=[
            self.repo.import_document({
                "title":f"附件 {i}",
                "content":f"附件 {i} 的唯一值是 ATTACH-{i}。"+(" detail"*400),
            })
            for i in range(4)
        ]
        sid=self.repo.create_session()["id"]
        rid=self.repo.create_turn(
            sid,
            "请详细阅读这些附件原文并给出处。",
            "v013-pinned-l2",
            document_ids=[item["id"] for item in docs],
        )["run_id"]
        snapshot=self.repo.turn(rid)["snapshot"]

        self.assertEqual(snapshot["intent_pick"]["route"],"local_retrieval")
        self.assertEqual(snapshot["information_resolution"]["resolution"],"L2")
        self.assertTrue({item["id"] for item in docs} <= {item["document_id"] for item in snapshot["knowledge"]})
        for item in snapshot["knowledge"]:
            if item["document_id"] in {doc["id"] for doc in docs}:
                self.assertEqual(item["resolution"],"L2")
                self.assertIn("@",item["source_ref"])

    def test_no_local_evidence_stays_agent_with_l0(self):
        sid=self.repo.create_session()["id"]
        rid=self.repo.create_turn(
            sid,
            "帮我分析一个新的产品方案。",
            "v013-agent-fallback",
        )["run_id"]
        snapshot=self.repo.turn(rid)["snapshot"]
        self.assertEqual(snapshot["intent_pick"]["route"],"agent")
        self.assertEqual(snapshot["information_resolution"]["resolution"],"L0")
        self.assertEqual(snapshot["knowledge"],[])

    def test_quick_eval_runner_executes_fixed_cases_and_release_gate(self):
        suite=Path(__file__).resolve().parents[1]/"evals"/"foundation-v1.json"
        result=FoundationEvalRunner.from_path(suite).run([
            "intent-arithmetic-local",
            "intent-ambiguous-fallback",
        ])
        self.assertEqual(result["report"]["pass_count"],2)
        self.assertEqual(result["report"]["fail_count"],0)
        self.assertTrue(result["release_gate"]["passed"])
        self.assertTrue(all(item["verdict"]=="PASS" for item in result["observations"]))

    def test_foundation_suite_has_executable_handler_for_every_fixed_case(self):
        suite=Path(__file__).resolve().parents[1]/"evals"/"foundation-v1.json"
        runner=FoundationEvalRunner.from_path(suite)
        for case in runner.suite.cases:
            self.assertTrue(
                hasattr(runner,f"_case_{case.case_id.replace('-','_')}"),
                case.case_id,
            )

    def test_evaluation_domain_is_usable_but_gain_remains_unpromoted(self):
        snapshot=MythComponents.default().snapshot()
        domains={item["id"]:item for item in snapshot["domains"]}
        self.assertEqual(domains["evaluation"]["maturity"],Maturity.USABLE.value)
        strategies={item["id"]:item for item in snapshot["strategies"]}
        self.assertEqual(strategies["information_resolution"]["maturity"],"connected")
        self.assertEqual(strategies["information_gain"]["maturity"],"exists")


if __name__=="__main__":
    unittest.main()
