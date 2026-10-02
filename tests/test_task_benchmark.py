import json
from pathlib import Path
import tempfile
import unittest

from myth.task_benchmark import run_task_benchmark


SUITE=Path(__file__).resolve().parents[1]/"evals"/"daily-v1.json"


class TaskBenchmarkTests(unittest.TestCase):
    def test_complete_fixed_suite_repeats_and_persists_both_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"evidence"
            report=run_task_benchmark(SUITE,output,repeats=3)
            self.assertTrue(report["complete_suite"])
            self.assertEqual(report["kind"],"harness_fixture")
            self.assertEqual(len(report["trials"]),60)
            self.assertTrue(all(t["success"] for t in report["trials"]))
            self.assertEqual(report["summary"]["myth"]["passed"],30)
            self.assertEqual(json.loads((output/"report.json").read_text(encoding="utf-8"))["suite_digest"],report["suite_digest"])
            self.assertTrue(all(Path(t["evidence_root"]).is_dir() for t in report["trials"]))
            with self.assertRaises(FileExistsError):run_task_benchmark(SUITE,output)

    def test_filtered_run_never_claims_complete_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=run_task_benchmark(SUITE,Path(tmp)/"filtered",repeats=1,case_ids=["arithmetic"])
            self.assertFalse(report["complete_suite"])
            self.assertEqual(len(report["trials"]),2)
            self.assertEqual(report["trials"][0]["model_calls"],0)
            self.assertEqual(report["trials"][1]["model_calls"],1)

    def test_wrong_completion_is_counted_by_artifact_bytes_not_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite=json.loads(SUITE.read_text(encoding="utf-8"))
            case=next(c for c in suite["cases"] if c["id"]=="artifact-text")
            case["steps"][0]["args"]["content"]="WRONG"
            path=Path(tmp)/"bad.json";path.write_text(json.dumps(suite),encoding="utf-8")
            report=run_task_benchmark(path,Path(tmp)/"bad",repeats=1,case_ids=["artifact-text"])
            self.assertTrue(all(t["status"]=="COMPLETED" for t in report["trials"]))
            self.assertTrue(all(t["completion_without_acceptance"] for t in report["trials"]))
            self.assertFalse(any(t["success"] for t in report["trials"]))

    def test_invalid_case_and_repeat_are_rejected_before_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            for repeats in (True,0,11):
                with self.assertRaises(ValueError):run_task_benchmark(SUITE,Path(tmp)/"unused",repeats=repeats)
            with self.assertRaises(ValueError):run_task_benchmark(SUITE,Path(tmp)/"unused",case_ids=["missing"])


if __name__=="__main__":unittest.main()
