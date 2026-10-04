"""回归边界：Mental Model 自动后台 Refresh 复用 Core Run / DecisionRuntime / DurableExecutor。
测试固定 opt-in、去重、水位、Lease、UNKNOWN、退避与发布；替身模型通过不等同真实供应商质量。
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from myth.models import ModelResult, ProviderStatus
from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace


# RefreshProvider：只返回固定 synthesis；可注入 Ticket 后异常或在 invoke 中改变 Memory 制造并发水位竞争。
class RefreshProvider:
    provider_id = "ollama"

    # 保存调用次数与可选副作用；副作用仅用于测试 prepare->commit 竞争窗口。
    def __init__(self, *, workspace=None, fail_after_ticket=False, mutate_source=False):
        # workspace：可选同线程测试装配；生产 Provider 不应直接写 Memory。
        self.workspace = workspace
        # fail_after_ticket：模拟请求已获 Ticket 后连接结果不明。
        self.fail_after_ticket = fail_after_ticket
        # mutate_source：在模型返回前追加来源变化，验证旧 synthesis 不发布。
        self.mutate_source = mutate_source
        # calls：替身真实 invoke 次数；用于证明 UNKNOWN 不被后台重复派发。
        self.calls = 0

    # check：只证明替身连通；不证明模型质量。
    def check(self):
        return ProviderStatus("ollama", True, auth_type="none", details={"models": ["test"]})

    # invoke：从固定请求里取 admitted source_ref，返回合法 request_completion wire。
    def invoke(self, request):
        self.calls += 1
        if self.fail_after_ticket:
            raise RuntimeError("ambiguous timeout after refresh Ticket")
        payload = json.loads(request.messages[-1].content)
        if self.mutate_source and self.workspace is not None:
            self.workspace.memory.remember(
                kind="semantic",
                text="A newer architecture fact arrived during synthesis.",
                source_ref="note:concurrent-refresh-change",
            )
        refs = [item["source_ref"] for item in payload["sources"][:2]]
        decision = {
            "decision_type": "request_completion",
            "reason": "Synthesize only admitted Memory evidence.",
            "capability_id": "",
            "arguments_json": "{}",
            "question": "",
            "missing_info_category": "",
            "claim": "Myth keeps durable evidence-backed knowledge current.",
            "goal_coverage": "mental-model-refresh",
            "evidence_refs": refs,
            "remaining": [],
        }
        return ModelResult(
            text=json.dumps(decision),
            usage={"model_calls": 1, "input_tokens": 120, "output_tokens": 40},
            raw={
                "id": f"refresh-{self.calls}",
                "provider": "ollama",
                "model": "test",
                "status": "completed",
                "usage": {"input_tokens": 120, "output_tokens": 40},
            },
            response_id=f"refresh-{self.calls}",
        )


# MentalModelAutoRefreshTests：每个用例使用独立 SQLite；后台语义必须从 durable facts 恢复而不是进程缓存。
class MentalModelAutoRefreshTests(unittest.TestCase):
    # 建立固定 Memory、Mental Model 与模型设置；默认未启用自动刷新。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.workspace.repository.save_settings(
            {
                "provider": "ollama",
                "model": "test",
                "max_output_tokens": 1024,
                "num_ctx": 8192,
            }
        )
        self.source = self.workspace.memory.remember(
            kind="semantic",
            text="Myth uses SQLite as authority and durable Evidence.",
            source_ref="decision:auto-refresh-source",
        )
        self.model = self.workspace.knowledge_views.create_model(
            name="Architecture",
            source_query="Myth SQLite Evidence",
        )
        self.refresh = self.workspace.mental_model_refresh

    # 关闭 Runtime，避免数据库连接跨测试；临时目录拥有所有模型收据。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 自动刷新必须显式 opt-in，并冻结配置时的 Provider/Model；全局设置后改不倒写 policy。
    def test_policy_is_opt_in_and_freezes_model_settings(self):
        self.assertEqual(self.refresh.due(), [])
        policy = self.refresh.configure(
            self.model["model_id"], enabled=True, min_interval_seconds=60
        )
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["settings"]["model"], "test")
        self.assertEqual(len(self.refresh.due()), 1)

        self.workspace.repository.save_settings(
            {"provider": "ollama", "model": "later-model", "num_ctx": 8192}
        )
        frozen = self.refresh.policy(self.model["model_id"])
        self.assertEqual(frozen["settings"]["model"], "test")

    # 同一个 source watermark 只准入一个 Core Run；pending occurrence 会吸收重复扫描。
    def test_same_watermark_coalesces_to_one_occurrence(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"], now=1000.0)
        again = self.refresh.admit(self.model["model_id"], now=1000.5)

        self.assertEqual(run_id, again)
        count = self.runtime.store.db.execute(
            "SELECT COUNT(*) AS n FROM mental_model_refresh_occurrences"
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    # per-occurrence lease 阻止双 worker；过期后新 owner 可接管同一 Run，而不是新建 occurrence。
    def test_refresh_lease_allows_only_one_live_owner(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"], now=1000.0)

        self.assertTrue(self.refresh.claim(run_id, "worker-a", ttl_seconds=8, now=1000.0))
        self.assertFalse(self.refresh.claim(run_id, "worker-b", ttl_seconds=8, now=1005.0))
        self.assertTrue(self.refresh.claim(run_id, "worker-b", ttl_seconds=8, now=1009.0))
        self.assertFalse(self.refresh.heartbeat(run_id, "worker-a", now=1010.0))
        self.assertTrue(self.refresh.heartbeat(run_id, "worker-b", now=1010.0))

    # 成功刷新走一次模型 Ticket/Receipt，提交 backing Memory 后 occurrence 与 Core Run 同为成功。
    def test_successful_refresh_commits_materialized_view_and_core_run(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"])
        provider = RefreshProvider()

        result = self.refresh.run(run_id, provider)

        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(self.runtime.store.get_run(run_id)["state"], "SUCCEEDED")
        model = self.workspace.knowledge_views.model(self.model["model_id"], resolution="L2")
        self.assertEqual(model["freshness"], "fresh")
        self.assertEqual(
            model["content"]["text"],
            "Myth keeps durable evidence-backed knowledge current.",
        )
        self.assertGreaterEqual(model["content"]["proof_count"], 1)

    # Ticket 后结果不明必须进入 UNKNOWN/RECOVERING；后续 due/dispatch 都不能绕过原模型机会。
    def test_unknown_refresh_is_never_auto_redispatched(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"])
        provider = RefreshProvider(fail_after_ticket=True)

        result = self.refresh.run(run_id, provider)

        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(self.runtime.store.get_run(run_id)["state"], "RECOVERING")
        self.assertEqual(self.refresh.dispatchable_runs(), [])
        self.assertEqual(self.refresh.due(), [])
        self.assertEqual(provider.calls, 1)

    # 旧 worker 在模型返回后失去 lease 时只能留下 Receipt；新 owner 消费同一 Receipt 完成发布。
    def test_lost_owner_cannot_publish_but_new_owner_reuses_receipt(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"])
        self.assertTrue(self.refresh.claim(run_id, "worker-a", ttl_seconds=30))

        refresh = self.refresh

        # LeaseLostProvider：模拟模型返回前旧 owner 已失租；用于验证 Receipt 与发布权分离。
        class LeaseLostProvider(RefreshProvider):
            # 模型返回前模拟新 owner 已接管；真实系统中这是旧 lease 过期后的 takeover。
            def invoke(self, request):
                result = super().invoke(request)
                with refresh.store.tx() as db:
                    db.execute(
                        "UPDATE mental_model_refresh_occurrences SET owner_id='worker-b',"
                        "lease_until=?,heartbeat_at=? WHERE run_id=?",
                        (time.time() + 60, time.time(), run_id),
                    )
                return result

        old = LeaseLostProvider()
        first = self.refresh.run(run_id, old, owner_id="worker-a")
        self.assertEqual(first["state"], "RUNNING")
        self.assertIsNone(
            self.workspace.knowledge_views.model(self.model["model_id"])["content"]
        )

        new = RefreshProvider()
        second = self.refresh.run(run_id, new, owner_id="worker-b")
        self.assertEqual(second["state"], "SUCCEEDED")
        self.assertEqual(old.calls, 1)
        self.assertEqual(new.calls, 0)

    # UNKNOWN 后迟到 Receipt 只恢复同一模型 Attempt；后续 commit 不得再次调用 Provider。
    def test_late_receipt_reconciles_same_run_without_provider_replay(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"])
        failing = RefreshProvider(fail_after_ticket=True)
        self.assertEqual(self.refresh.run(run_id, failing)["state"], "UNKNOWN")

        invocation = self.runtime.store.db.execute(
            "SELECT * FROM model_invocations WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        prepared = self.workspace.knowledge_views.prepare_refresh(
            self.model["model_id"], limit=12, resolution="L1"
        )
        source_ref = prepared["sources"][0]["source_ref"]
        decision = {
            "decision_type": "request_completion",
            "reason": "Late but durable synthesis response.",
            "capability_id": "",
            "arguments_json": "{}",
            "question": "",
            "missing_info_category": "",
            "claim": "Late receipt safely resumes the same refresh.",
            "goal_coverage": "mental-model-refresh",
            "evidence_refs": [source_ref],
            "remaining": [],
        }
        raw = {
            "id": "late-refresh-response",
            "provider": "ollama",
            "model": "test",
            "status": "completed",
        }
        response_ref = self.runtime.objects.put(
            json.dumps(raw, sort_keys=True).encode("utf-8")
        )
        receipt = {
            "model_attempt_id": invocation["model_attempt_id"],
            "request_digest": invocation["request_digest"],
            "response_ref": response_ref,
            "response_id": "late-refresh-response",
            "text": json.dumps(decision),
            "usage": {
                "model_calls": 1,
                "input_tokens": 120,
                "output_tokens": 40,
            },
        }
        self.workspace.repository.decisions._receipt_path(
            invocation["model_attempt_id"]
        ).write_text(json.dumps(receipt), encoding="utf-8")

        reconciled = self.refresh.reconcile_unknown()
        self.assertEqual(reconciled[0]["state"], "ADMITTED")

        should_not_run = RefreshProvider()
        result = self.refresh.run(run_id, should_not_run)
        self.assertEqual(result["state"], "SUCCEEDED")
        self.assertEqual(should_not_run.calls, 0)
        self.assertEqual(self.runtime.store.get_run(run_id)["state"], "SUCCEEDED")

    # 模型调用期间来源水位变化时，旧 synthesis 已有收据但不能发布；Run 明确 SUPERSEDED/CANCELLED。
    def test_source_change_during_synthesis_supersedes_old_refresh(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"])
        provider = RefreshProvider(workspace=self.workspace, mutate_source=True)

        result = self.refresh.run(run_id, provider)

        self.assertEqual(result["state"], "SUPERSEDED")
        self.assertEqual(self.runtime.store.get_run(run_id)["state"], "CANCELLED")
        current = self.workspace.knowledge_views.model(self.model["model_id"], resolution="L2")
        self.assertEqual(current["freshness"], "unmaterialized")
        self.assertIsNone(current["content"])

    # Web 产品门面可直接创建 Mental Model 并打开 auto-refresh；用户不需要 Python/PowerShell 才能使用。
    def test_web_facade_exposes_mental_model_auto_refresh(self):
        service = ConversationWebService(self.root)
        created = service.post(
            ["mental-models"],
            {
                "name": "Web knowledge",
                "source_query": "Myth SQLite Evidence",
            },
        )
        configured = service.post(
            ["mental-models", created["model_id"], "auto-refresh"],
            {"enabled": True, "min_interval_seconds": 60},
        )
        listed = service.get(["mental-models"], {})["mental_models"]

        self.assertTrue(configured["enabled"])
        selected = next(
            item for item in listed if item["model_id"] == created["model_id"]
        )
        self.assertTrue(selected["auto_refresh"]["enabled"])

    # 已知 FAILED 退避后可在同一 source watermark 建 attempt #2；UNKNOWN 则仍被永久挡在自动重试外。
    def test_known_failure_can_retry_same_watermark_as_new_attempt(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        first_run = self.refresh.admit(self.model["model_id"], now=1000.0)

        # NoEvidenceProvider：返回结构合法但无底层 Evidence 的已知坏 synthesis；用于验证失败后退避重试。
        class NoEvidenceProvider(RefreshProvider):
            # 返回结构合法但没有底层 Evidence 的 synthesis；Runtime 应已知失败而不是 UNKNOWN。
            def invoke(self, request):
                self.calls += 1
                decision = {
                    "decision_type": "request_completion",
                    "reason": "Invalid fixture without evidence.",
                    "capability_id": "",
                    "arguments_json": "{}",
                    "question": "",
                    "missing_info_category": "",
                    "claim": "Unsupported synthesis.",
                    "goal_coverage": "mental-model-refresh",
                    "evidence_refs": [],
                    "remaining": [],
                }
                return ModelResult(
                    text=json.dumps(decision),
                    usage={"model_calls": 1, "input_tokens": 30, "output_tokens": 10},
                    raw={"id": "no-evidence", "status": "completed"},
                    response_id="no-evidence",
                )

        failed = self.refresh.run(first_run, NoEvidenceProvider())
        self.assertEqual(failed["state"], "FAILED")
        policy = self.refresh.policy(self.model["model_id"])

        second_run = self.refresh.admit(
            self.model["model_id"], now=float(policy["retry_at"]) + 0.1
        )
        self.assertIsNotNone(second_run)
        self.assertNotEqual(second_run, first_run)
        second = self.refresh.occurrence(second_run)
        self.assertEqual(second["source_change_seq"], failed["source_change_seq"])
        self.assertEqual(second["attempt_no"], 2)

    # policy retry_at 必须约束已准入 occurrence 的重新派发，不能每两秒忽略退避再次探测。
    def test_dispatchable_respects_policy_backoff(self):
        self.refresh.configure(self.model["model_id"], enabled=True, min_interval_seconds=60)
        run_id = self.refresh.admit(self.model["model_id"], now=1000.0)
        self.refresh.defer(self.model["model_id"], "provider disconnected")
        policy = self.refresh.policy(self.model["model_id"])

        self.assertGreater(policy["retry_at"], time.time())
        self.assertNotIn(run_id, self.refresh.dispatchable_runs(now=time.time()))
        self.assertIn(run_id, self.refresh.dispatchable_runs(now=policy["retry_at"] + 0.1))


if __name__ == "__main__":
    unittest.main()
