from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.platform.evaluation import (
    EvalObservation,
    EvalVerdict,
    release_gate,
    summarize_observations,
)
from myth.runtime import MythRuntime
from myth.workspace import Workspace


class RetrievalEvalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.runtime=MythRuntime(self.root)
        self.workspace=Workspace(self.runtime)
        self.repo=self.workspace.repository
        self.repo.save_settings({"provider":"ollama","model":"test"})

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def test_knowledge_search_can_find_candidate_after_former_10000_cutoff(self):
        doc=self.repo.import_document({"title":"bulk","content":"seed"})
        rows=[(doc["id"],i,"noise") for i in range(1,10002)]
        rows.append((doc["id"],10002,"needle AFTER-CUTOFF-77"))
        with self.runtime.store.tx() as db:
            db.executemany(
                "INSERT INTO workspace_chunks(document_id,chunk_index,content) VALUES (?,?,?)",
                rows,
            )
        report=self.repo.search_report("AFTER-CUTOFF-77",limit=3)
        self.assertGreater(report["retrieval"]["scanned"],10000)
        self.assertTrue(report["retrieval"]["exhausted"])
        self.assertFalse(report["retrieval"]["truncated_before_ranking"])
        self.assertEqual(report["sources"][0]["chunk_index"],10002)

    def test_memory_search_can_find_visible_record_after_former_500_cutoff(self):
        with self.runtime.store.tx() as db:
            db.executemany(
                "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                "VALUES (?,?,?,?,?,?,?)",
                [
                    (f"mem_bulk_{i}","semantic","noise",f"bulk:{i}","global",None,"context")
                    for i in range(505)
                ],
            )
            db.execute(
                "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id,fact_level) "
                "VALUES (?,?,?,?,?,?,?)",
                ("mem_target","semantic","memory AFTER-MEMORY-500","bulk:target","global",None,"verified"),
            )
        report=self.workspace.memory.search_report("AFTER-MEMORY-500",limit=3)
        self.assertGreater(report["retrieval"]["scanned"],500)
        self.assertTrue(report["retrieval"]["exhausted"])
        self.assertEqual(report["memories"][0]["memory_id"],"mem_target")

    def test_project_search_reports_cursor_and_scan_coverage(self):
        project_root=self.root/"project"
        project_root.mkdir()
        for i in range(3):
            (project_root/f"{i}.txt").write_text(
                "needle\n" if i==2 else "noise\n",
                encoding="utf-8",
            )
        project=self.repo.create_project({"name":"p","root":str(project_root)})
        sid=self.repo.create_session(project_id=project["id"])["id"]
        rid=self.repo.create_turn(sid,"find needle","req-project-cursor")["run_id"]
        turn=self.repo.turn(rid)

        first=self.workspace.execution._search_project(
            turn,{"query":"needle","max_files":1,"limit":5}
        )
        self.assertEqual(first["scanned_files"],1)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["matches"],[])

        second=self.workspace.execution._search_project(
            turn,{
                "query":"needle",
                "cursor":first["next_cursor"],
                "max_files":2,
                "limit":5,
            },
        )
        self.assertEqual(second["scanned_files"],2)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["matches"][0]["path"],"2.txt")

    def test_resolution_levels_keep_one_source_digest(self):
        doc=self.repo.import_document({
            "title":"guide",
            "content":"alpha\n"+"beta "*700,
        })
        sid=self.repo.create_session()["id"]
        rid=self.repo.create_turn(sid,"inspect guide","req-resolutions")["run_id"]
        turn=self.repo.turn(rid)
        views=[
            self.workspace.execution._resolve_knowledge(
                turn,{"document_id":doc["id"],"resolution":level}
            )
            for level in ("L0","L1","L2")
        ]
        self.assertEqual({view["source_ref"] for view in views}, {f"doc:{doc['id']}@{doc['digest']}"})
        self.assertEqual([view["resolution"] for view in views],["L0","L1","L2"])
        self.assertIn("chunks",views[1])
        self.assertIn("content",views[2])

    def test_eval_report_preserves_unsupported_and_safety_evidence(self):
        report=summarize_observations("foundation",[
            EvalObservation("a",EvalVerdict.PASS,"ok",{"cost":2},("run:a",)),
            EvalObservation("b",EvalVerdict.UNSUPPORTED,"adapter missing"),
        ])
        self.assertEqual(report.pass_count,1)
        self.assertEqual(report.unsupported_count,1)
        self.assertEqual(report.measured_cost,2)
        self.assertFalse(release_gate(report)[0])

        safe=summarize_observations("foundation",[
            EvalObservation("a",EvalVerdict.PASS,"ok"),
            EvalObservation("b",EvalVerdict.PASS,"ok"),
        ])
        self.assertTrue(release_gate(safe,min_pass_rate=1.0)[0])


if __name__ == "__main__":
    unittest.main()
