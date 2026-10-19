"""The Last Mile：重复试次统计、固定 Suite 证据和双阶段只读复核。

全部“真实 Provider”标签均为离线合成输入；测试只证明逻辑与拒绝条件，
不证明任何外部模型已被调用、模型权重真实固定或任务获得了统计独立性。
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from myth.context_release_review import review_context_release
from myth.domain import digest_json
from myth.platform.trial_statistics import case_clustered_sign_test
from myth.task_benchmark import CONTEXT_BENCHMARK_ARMS, summarize_context_ablation


class ContextReleaseLastMileTests(unittest.TestCase):
    """使用显式临时目录和合成试次，检验双阶段报告能拒绝不完整/伪统计结论。"""

    # 每个测试有唯一临时证据目录；模拟器不访问模型/网络。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    # 关闭本例目录资源；不影响其他测试或正式项目状态。
    def tearDown(self):
        self.tmp.cleanup()

    # 在临时 SQLite、不可变对象和模型收据中写入同一次虚拟调用，测试核对不依赖报告自述。
    def synthetic_receipt(self, evidence, run_id, attempt, activation, usage):
        request = {
            "model": "test-model:exact",
            "messages": [{"role": "user", "content": "synthetic request fixture"}],
            "response_schema": {},
            "max_output_tokens": 128,
            "thinking": False,
            "num_ctx": 8192,
            "temperature": 0.0,
            "context_report": {
                "governance": {
                    "causality": activation["causality"],
                    "relevance": activation["relevance"],
                },
                "context_mode": "normal", "selected": [], "bytes_used": 120,
            }
        }
        objects = evidence / "objects"
        # 写入哈希命名且字节身份可复查的虚拟对象，不接触正式 Runtime 数据。
        def write_object(value):
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            digest = hashlib.sha256(payload).hexdigest()
            dest = objects / digest[:2] / digest[2:]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            return digest

        request_ref = write_object(request)
        response_ref = write_object({"status": "synthetic"})
        # 合成票据也必须绑定真实冻结请求内容；随机尝试身份不能替代模型请求摘要。
        request_digest = digest_json(request)
        with closing(sqlite3.connect(evidence / "runtime.db")) as db, db:
            db.execute("CREATE TABLE workspace_turns(run_id TEXT PRIMARY KEY,status TEXT)")
            db.execute(
                "CREATE TABLE model_invocations("
                "model_attempt_id TEXT,run_id TEXT,provider_id TEXT,model_id TEXT,"
                "state TEXT,outcome TEXT,ticket_id TEXT,response_ref TEXT,"
                "request_ref TEXT,request_digest TEXT,usage_json TEXT,response_id TEXT)"
            )
            db.execute(
                "INSERT INTO workspace_turns(run_id,status) VALUES (?,?)", (run_id, "COMPLETED")
            )
            db.execute(
                "INSERT INTO model_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt, run_id, "ollama", "test-model:exact", "RESOLVED", "SUCCEEDED",
                    "ticket_fixture", response_ref, request_ref, request_digest,
                    json.dumps(usage), "synthetic_response",
                ),
            )
        journal = evidence / "model-receipts"
        journal.mkdir()
        (journal / f"{attempt}.json").write_text(
            json.dumps({
                "model_attempt_id": attempt,
                "request_digest": request_digest,
                "response_ref": response_ref,
                "response_id": "synthetic_response",
                "usage": usage,
            }),
            encoding="utf-8",
        )

    # 用 case×repeat×arm 原子格构造一致的合成报告，刻意固定所有环境身份。
    def bundle(self, name, partition, *, prefix=None, case_count=7, repeats=3,
               model_digest="ollama-test-pin", source_digest="a" * 64):
        root = self.root / name
        root.mkdir()
        identity = prefix or name
        ids = [f"{identity}-{index}" for index in range(case_count)]
        suite = {
            "suite_id": f"{name}-v1", "partition": partition,
            "cases": [{"id": case_id, "category": "fixed", "acceptance": {}}
                      for case_id in ids],
        }
        arms = tuple(CONTEXT_BENCHMARK_ARMS)
        trials = []
        for repeat in range(1, repeats + 1):
            for case_id in ids:
                for arm in arms:
                    evidence = root / f"{repeat}-{case_id}-{arm}" / ".runtime"
                    evidence.mkdir(parents=True)
                    run_id = f"run_{repeat}_{case_id}_{arm}"
                    attempt = f"model_{repeat}_{case_id}_{arm}"
                    activation = {
                        "model_attempt_id": attempt,
                        "causality": (
                            "causal-active-set-v2"
                            if arm in {"context-causal", "context-full"}
                            else "disabled-for-controlled-evaluation"
                        ),
                        "relevance": (
                            "cross-source-bounded-lexical-candidate-ranking"
                            if arm in {"context-relevance", "context-full"}
                            else "disabled-for-controlled-evaluation"
                        ),
                        "context_mode": "normal", "selected": 0, "bytes_used": 120,
                    }
                    usage = {
                        "input_tokens": 100 if arm == "context-full" else 150,
                        "output_tokens": 20,
                        "cached_input_tokens": 0,
                        "provider_wall_ms": 300 if arm == "context-full" else 400,
                    }
                    self.synthetic_receipt(evidence, run_id, attempt, activation, usage)
                    trials.append({
                        "case_id": case_id, "repeat": repeat, "arm": arm,
                        "success": True, "status": "COMPLETED", "model_calls": 1,
                        "human_takeover": False, "repeated_tool_calls": 0,
                        "run_ids": [run_id],
                        "evidence_root": str(evidence),
                        "context_activation": [activation],
                        "usage_measured": usage,
                        "usage_samples": {key: 1 for key in usage},
                        "measured_model_attempts": 1,
                    })
        report = {
            "suite_id": suite["suite_id"],
            "suite_digest": digest_json(suite),
            "source_digest": source_digest,
            "runtime_version": "0.27.0",
            "provider": "ollama", "model": "test-model:exact",
            "model_metadata": {"digest": model_digest} if model_digest else None,
            "settings": {"temperature": 0.0, "thinking": False},
            "repeats": repeats, "arms": list(arms), "kind": "real_provider",
            "partition": "declared_heldout" if partition == "heldout" else "discovery",
            "suite_case_count": len(ids), "selected_case_count": len(ids),
            "complete_suite": True,
            "planned_trials": len(trials),
            "trials": trials,
        }
        report["context_ablation"] = summarize_context_ablation(
            trials, arms, tuple(ids), repeats, kind="real_provider", complete_suite=True,
        )
        (root / "suite.json").write_text(
            json.dumps(suite, ensure_ascii=False), encoding="utf-8",
        )
        self.save_report(root, report)
        return root

    # 模拟原子保存后的报告版本；复核时会逐字段重新核算。
    def save_report(self, root, report):
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8",
        )

    # 三次重跑同 Case 只贡献一次统计符号，不能凭重跑次数夸大独立样本。
    def test_repeated_one_case_is_not_statistical_evidence(self):
        pairs = [
            {"case_id": "only", "repeat": index, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -4}}}
            for index in range(1, 11)
        ]
        result = case_clustered_sign_test(pairs, ("only",), 10)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["discordant_cases"], 1)
        self.assertEqual(result["p_one_sided"], 0.5)
        self.assertFalse(result["passed"])

    # 六个真正不同的 Case 全部改善且有三次重复时单侧精确 p=1/64。
    def test_six_distinct_cases_have_an_exact_one_sided_p_value(self):
        cases = tuple(f"case-{i}" for i in range(6))
        pairs = [
            {"case_id": case_id, "repeat": repeat, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -1}}}
            for case_id in cases for repeat in range(1, 4)
        ]
        result = case_clustered_sign_test(pairs, cases, 3)
        self.assertTrue(result["passed"])
        self.assertEqual(result["discordant_cases"], 6)
        self.assertEqual(result["p_one_sided"], 1 / 64)
        self.assertEqual(len(result["case_cost_deltas"]), 6)

    # 相同 Case/Repeat 的重复上报或缺测成本都使完整分母失败。
    def test_duplicate_or_missing_paired_samples_fail_closed(self):
        cases = tuple(f"case-{i}" for i in range(7))
        pairs = [
            {"case_id": case_id, "repeat": repeat, "status": "PAIRED",
             "measured_cost": {"input_tokens": {"delta": -1}}}
            for case_id in cases for repeat in range(1, 4)
        ]
        duplicate = case_clustered_sign_test(pairs + [pairs[0]], cases, 3)
        self.assertFalse(duplicate["passed"])
        self.assertTrue(duplicate["invalid_pairs"])
        missing = case_clustered_sign_test(pairs[:-1], cases, 3)
        self.assertFalse(missing["passed"])
        self.assertEqual(len(missing["missing_pairs"]), 1)

    # 两个真实模型报告形状可以进入人工复核，但合成测试绝不授予生产发布许可。
    def test_discovery_and_heldout_recompute_to_manual_review(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "READY_FOR_MANUAL_REVIEW")
        self.assertFalse(result["promotion_eligible"])
        self.assertEqual(result["heldout"]["paired_significance"]["p_one_sided"], 1 / 128)
        self.assertTrue(result["evidence_digest"].startswith("sha256:"))

    # 改动 Trial 后不更新汇总不可掩盖：复核用原始格子重新计算后拒绝不一致。
    def test_report_summary_tampering_is_rejected(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        raw = json.loads((final / "report.json").read_text(encoding="utf-8"))
        raw["trials"][0]["success"] = False
        self.save_report(final, raw)
        with self.assertRaisesRegex(ValueError, "summary differs"):
            review_context_release(discovery, final)

    # Discovery/heldout 即使有两个 Suite 名称，同题身份重叠也不能自称独立验证。
    def test_case_overlap_returns_hold(self):
        discovery = self.bundle("discovery", "discovery", prefix="same")
        final = self.bundle("heldout", "heldout", prefix="same")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("overlap" in reason for reason in result["reasons"]))

    # 真实模型版本必须一致且可核对；名称相同而权重 digest 缺失/变化时停止晋升。
    def test_model_digest_missing_or_changed_returns_hold(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout", model_digest="other-digest")
        result = review_context_release(discovery, final)
        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("model weight digest" in reason for reason in result["reasons"]))

    # 完整证据必须能在本地回读，不能把缺失 .runtime 的摘要冒充收据原件。
    def test_missing_evidence_directory_is_rejected(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        raw = json.loads((final / "report.json").read_text(encoding="utf-8"))
        missing = Path(raw["trials"][0]["evidence_root"]) / "runtime.db"
        missing.unlink()
        with self.assertRaisesRegex(ValueError, "SQLite receipt database is missing"):
            review_context_release(discovery, final)

    # 只改报告的实测 Token 即使连汇总一并改写，也不能绕过 SQLite Receipt 用量核对。
    def test_report_cost_cannot_override_sqlite_receipt(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        report = json.loads((final / "report.json").read_text(encoding="utf-8"))
        report["trials"][0]["usage_measured"]["input_tokens"] = 1
        self.save_report(final, report)
        with self.assertRaisesRegex(ValueError, "usage totals differ"):
            review_context_release(discovery, final)

    # 删除原始模型收据使发布复核拒绝，目录本身存在不足以证明 Provider 返回结果。
    def test_missing_original_model_receipt_blocks_review(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        report = json.loads((final / "report.json").read_text(encoding="utf-8"))
        evidence = Path(report["trials"][0]["evidence_root"])
        next((evidence / "model-receipts").iterdir()).unlink()
        with self.assertRaisesRegex(ValueError, "receipt journal is missing"):
            review_context_release(discovery, final)

    # Context 启用声明必须和保存的原始请求逐项一致，不能只伪造展示用 activation。
    def test_context_activation_mismatch_blocks_review(self):
        discovery = self.bundle("discovery", "discovery")
        final = self.bundle("heldout", "heldout")
        report = json.loads((final / "report.json").read_text(encoding="utf-8"))
        report["trials"][0]["context_activation"][0]["causality"] = "forged-mode"
        self.save_report(final, report)
        with self.assertRaisesRegex(ValueError, "activation contradicts"):
            review_context_release(discovery, final)

    # 对象本身的 SHA 路径可校验，仍必须核对该对象与 Ticket 的 canonical digest 是否相同。
    def test_request_object_is_bound_to_ticket_digest(self):
        # 本例只检查单请求身份：每套 1 Case × 3 Repeat × 4 Arm 足以触发同一复核链。
        # 避免重复生成 7 Case 的上百套 SQLite，特别是 Windows 的同步写开销。
        discovery = self.bundle("discovery", "discovery", case_count=1)
        final = self.bundle("heldout", "heldout", case_count=1)
        report = json.loads((final / "report.json").read_text(encoding="utf-8"))
        evidence = Path(report["trials"][0]["evidence_root"])
        with closing(sqlite3.connect(evidence / "runtime.db")) as db, db:
            attempt, old_ref = db.execute(
                "SELECT model_attempt_id,request_ref FROM model_invocations"
            ).fetchone()
            old_path = evidence / "objects" / old_ref[:2] / old_ref[2:]
            request = json.loads(old_path.read_text(encoding="utf-8"))
            request["messages"][0]["content"] = "forged model-visible prompt"
            raw = json.dumps(request, ensure_ascii=False).encode("utf-8")
            new_ref = hashlib.sha256(raw).hexdigest()
            new_path = evidence / "objects" / new_ref[:2] / new_ref[2:]
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(raw)
            # 故意保留旧 Ticket/Receipt 所声称的 request_digest，模拟证据链断裂。
            db.execute(
                "UPDATE model_invocations SET request_ref=? WHERE model_attempt_id=?",
                (new_ref, attempt),
            )
        with self.assertRaisesRegex(ValueError, "request digest differs"):
            review_context_release(discovery, final)

    # 即使同时更新 Ticket/Receipt 的自洽摘要，真实请求型号也必须和受控实验冻结型号一致。
    def test_request_model_identity_cannot_be_changed(self):
        # 本例只检查单请求身份：每套 1 Case × 3 Repeat × 4 Arm 足以触发同一复核链。
        # 避免重复生成 7 Case 的上百套 SQLite，特别是 Windows 的同步写开销。
        discovery = self.bundle("discovery", "discovery", case_count=1)
        final = self.bundle("heldout", "heldout", case_count=1)
        report = json.loads((final / "report.json").read_text(encoding="utf-8"))
        evidence = Path(report["trials"][0]["evidence_root"])
        with closing(sqlite3.connect(evidence / "runtime.db")) as db, db:
            attempt, old_ref = db.execute(
                "SELECT model_attempt_id,request_ref FROM model_invocations"
            ).fetchone()
            old_path = evidence / "objects" / old_ref[:2] / old_ref[2:]
            request = json.loads(old_path.read_text(encoding="utf-8"))
            request["model"] = "different-model"
            raw = json.dumps(request, ensure_ascii=False).encode("utf-8")
            new_ref = hashlib.sha256(raw).hexdigest()
            new_path = evidence / "objects" / new_ref[:2] / new_ref[2:]
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_bytes(raw)
            new_digest = digest_json(request)
            db.execute(
                "UPDATE model_invocations SET request_ref=?,request_digest=? "
                "WHERE model_attempt_id=?",
                (new_ref, new_digest, attempt),
            )
            receipt_path = evidence / "model-receipts" / (attempt + ".json")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["request_digest"] = new_digest
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "request model differs"):
            review_context_release(discovery, final)

    # 单次测试即使所有成本下降也不具备对照统计效力。
    def test_single_repeat_report_is_rejected(self):
        discovery = self.bundle("discovery", "discovery", repeats=1)
        final = self.bundle("heldout", "heldout")
        with self.assertRaisesRegex(ValueError, "repeated trials"):
            review_context_release(discovery, final)


if __name__ == "__main__":
    unittest.main()
