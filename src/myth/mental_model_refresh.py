"""Mental Model 自动刷新调度与持久工作协调。
本模块只拥有 auto-refresh policy / occurrence；Mental Model 内容仍归 Knowledge Views，
模型调用复用 DecisionRuntime 的 Run/Ticket/Receipt/UNKNOWN，后台驱动复用 DurableExecutor。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .domain import RunState, canonical_json, digest_json, RecoveryRequired
from .models import ModelMessage, ModelRequest, STEP_DECISION_SCHEMA, ProviderUnavailable


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS mental_model_refresh_policies(
    model_id TEXT PRIMARY KEY REFERENCES workspace_mental_models(model_id),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    min_interval_seconds INTEGER NOT NULL DEFAULT 300,
    settings_json TEXT NOT NULL,
    retry_at REAL NOT NULL DEFAULT 0,
    retry_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mental_model_refresh_occurrences(
    occurrence_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL REFERENCES workspace_mental_models(model_id),
    source_change_seq INTEGER NOT NULL,
    model_revision INTEGER NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    state TEXT NOT NULL CHECK(state IN ('ADMITTED','RUNNING','SUCCEEDED','FAILED','UNKNOWN','SUPERSEDED')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    error TEXT,
    owner_id TEXT,
    lease_until REAL,
    heartbeat_at REAL,
    UNIQUE(model_id, source_change_seq)
);
CREATE INDEX IF NOT EXISTS idx_mm_refresh_occurrences_state
    ON mental_model_refresh_occurrences(state, updated_at);
"""


# _retry_delay：后台刷新失败退避与网络恢复保持同量级，但不高频轰炸供应商。
def _retry_delay(failures: int) -> float:
    steps = (5, 15, 30, 60, 120, 300, 600)
    return float(steps[min(max(1, int(failures)), len(steps)) - 1])


# MentalModelRefreshScheduler：把 stale 派生状态转成显式、可恢复的 Core Run，不直接执行供应商 I/O。
class MentalModelRefreshScheduler:
    # 复用 Workspace 已有 Knowledge Views、DecisionRuntime 与 Core Store；构造只建表，不启动线程。
    def __init__(self, workspace) -> None:
        # workspace：产品装配根；提供唯一 Memory/Knowledge/DecisionRuntime 状态所有者。
        self.workspace = workspace
        # store：Core/Workspace 共用 SQLite；policy/occurrence 只在本模块写。
        self.store = workspace.repository.store
        # views：Mental Model materialized view 所有者；refresh 只通过其公开 prepare/commit 接口。
        self.views = workspace.knowledge_views
        # decisions：模型 Ticket/Receipt/UNKNOWN 协调器；自动刷新不另造模型调用协议。
        self.decisions = workspace.repository.decisions
        self.store.db.executescript(SCHEMA)
        # additive migration：旧实验库补齐 per-occurrence lease；不存在历史 owner 时视为可接管。
        columns = {
            row["name"]
            for row in self.store.db.execute(
                "PRAGMA table_info(mental_model_refresh_occurrences)"
            ).fetchall()
        }
        with self.store.tx() as db:
            if "owner_id" not in columns:
                db.execute(
                    "ALTER TABLE mental_model_refresh_occurrences ADD COLUMN owner_id TEXT"
                )
            if "lease_until" not in columns:
                db.execute(
                    "ALTER TABLE mental_model_refresh_occurrences ADD COLUMN lease_until REAL"
                )
            if "heartbeat_at" not in columns:
                db.execute(
                    "ALTER TABLE mental_model_refresh_occurrences ADD COLUMN heartbeat_at REAL"
                )

    # configure：显式 opt-in/out，并冻结当前模型设置；自动刷新不会随全局设置悄悄换模型。
    def configure(
        self,
        model_id: str,
        *,
        enabled: bool,
        min_interval_seconds: int = 300,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if type(min_interval_seconds) is not int or not 60 <= min_interval_seconds <= 86400:
            raise ValueError("min_interval_seconds must be 60-86400")
        self.views.model(model_id, resolution="L0")
        fixed = dict(settings or self.workspace.repository.settings())
        if not str(fixed.get("provider") or "").strip() or not str(fixed.get("model") or "").strip():
            raise ValueError("auto refresh requires a selected provider/model")
        clean = {
            "provider": str(fixed["provider"]),
            "model": str(fixed["model"]),
            "ollama_url": str(fixed.get("ollama_url") or "http://127.0.0.1:11434"),
            "max_output_tokens": min(8192, max(256, int(fixed.get("max_output_tokens") or 2048))),
            "thinking": fixed.get("thinking"),
            "num_ctx": int(fixed.get("num_ctx") or 8192),
            "temperature": float(fixed.get("temperature") or 0.0),
        }
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO mental_model_refresh_policies("
                "model_id,enabled,min_interval_seconds,settings_json,retry_at,retry_failures,last_error"
                ") VALUES (?,?,?,?,0,0,NULL) "
                "ON CONFLICT(model_id) DO UPDATE SET enabled=excluded.enabled,"
                "min_interval_seconds=excluded.min_interval_seconds,settings_json=excluded.settings_json,"
                "retry_at=0,retry_failures=0,last_error=NULL,updated_at=CURRENT_TIMESTAMP",
                (model_id, int(enabled), min_interval_seconds, canonical_json(clean)),
            )
        return self.policy(model_id)

    # policy：返回冻结设置与最近 occurrence；enabled 只是未来触发资格，不代表当前正在执行。
    def policy(self, model_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM mental_model_refresh_policies WHERE model_id=?", (model_id,)
        ).fetchone()
        if row is None:
            raise KeyError(model_id)
        value = dict(row)
        value["enabled"] = bool(value["enabled"])
        value["settings"] = json.loads(value.pop("settings_json"))
        last = self.store.db.execute(
            "SELECT * FROM mental_model_refresh_occurrences WHERE model_id=? ORDER BY created_at DESC LIMIT 1",
            (model_id,),
        ).fetchone()
        value["last_occurrence"] = None if last is None else dict(last)
        return value

    # due：只选 stale/unmaterialized、超过最小间隔且没有未决 occurrence 的模型；同一变化水位只会形成一个机会。
    def due(self, *, now: float | None = None, limit: int = 8) -> list[dict[str, Any]]:
        now = time.time() if now is None else float(now)
        rows = self.store.db.execute(
            "SELECT model_id FROM mental_model_refresh_policies "
            "WHERE enabled=1 AND retry_at<=? ORDER BY updated_at,model_id LIMIT ?",
            (now, max(1, min(int(limit), 64))),
        ).fetchall()
        due = []
        for row in rows:
            model_id = str(row["model_id"])
            policy = self.policy(model_id)
            model = self.views.model(model_id, resolution="L0")
            if model["freshness"] == "fresh" or not model.get("active"):
                continue
            pending = self.store.db.execute(
                "SELECT 1 FROM mental_model_refresh_occurrences WHERE model_id=? "
                "AND state IN ('ADMITTED','RUNNING','UNKNOWN') LIMIT 1",
                (model_id,),
            ).fetchone()
            if pending:
                continue
            last = policy.get("last_occurrence")
            if last and now - float(last["created_at"]) < int(policy["min_interval_seconds"]):
                continue
            due.append({"model": model, "policy": policy})
        return due

    # admit：固定 prepare 快照、水位与模型预算，先创建 Core Run，再登记唯一 occurrence；同水位竞争只成功一次。
    def admit(self, model_id: str, *, now: float | None = None) -> str | None:
        now = time.time() if now is None else float(now)
        policy = self.policy(model_id)
        if not policy["enabled"] or policy["retry_at"] > now:
            return None
        prepared = self.views.prepare_refresh(model_id, limit=12, resolution="L1")
        source_change_seq = int(prepared["observed_change_seq"])
        if not prepared["sources"]:
            self.defer(model_id, "no admissible Memory sources for refresh")
            return None
        existing = self.store.db.execute(
            "SELECT run_id,state FROM mental_model_refresh_occurrences "
            "WHERE model_id=? AND source_change_seq=?",
            (model_id, source_change_seq),
        ).fetchone()
        if existing:
            return str(existing["run_id"]) if existing["state"] in {"ADMITTED","RUNNING"} else None

        settings = policy["settings"]
        run_id = f"run_{uuid.uuid4().hex}"
        occurrence_id = f"mmr_{uuid.uuid4().hex}"
        entry = {
            "kind": "mental_model_refresh",
            "model_id": model_id,
            "model_revision": int(prepared["model_revision"]),
            "source_change_seq": source_change_seq,
            "provider": settings["provider"],
            "model": settings["model"],
        }
        budgets = {
            "model_calls": 1,
            "input_tokens": 2_000_000,
            "output_tokens": int(settings["max_output_tokens"]),
        }
        request_id = f"mental-model-refresh:{model_id}:{source_change_seq}"
        with self.store.tx() as db:
            existing_run = self.store.request_run(request_id, digest_json(entry))
            if existing_run is not None:
                return existing_run
            admitted, created = self.store.create_run(
                run_id=run_id,
                request_id=request_id,
                entry_digest=digest_json(entry),
                goal=f"Refresh Mental Model {prepared['name']}: {prepared['source_query']}",
                acceptance_version="mental-model-refresh-v1",
                budgets=budgets,
                _db=db,
            )
            if not created:
                return admitted
            db.execute(
                "INSERT INTO mental_model_refresh_occurrences("
                "occurrence_id,model_id,source_change_seq,model_revision,run_id,state,created_at,updated_at"
                ") VALUES (?,?,?,?,?,'ADMITTED',?,?)",
                (
                    occurrence_id,
                    model_id,
                    source_change_seq,
                    int(prepared["model_revision"]),
                    run_id,
                    now,
                    now,
                ),
            )
            self.store._event(
                db,
                run_id,
                "MentalModelRefreshAdmitted",
                {
                    "model_id": model_id,
                    "source_change_seq": source_change_seq,
                    "model_revision": int(prepared["model_revision"]),
                },
            )
        return run_id

    # occurrence：读取 refresh 工作身份；Run 状态与 occurrence 状态都保留，不能只看其中一个猜结果。
    def occurrence(self, run_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM mental_model_refresh_occurrences WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    # dispatchable_runs：只返回策略退避已到且 occurrence lease 空闲/过期的工作；UNKNOWN 永不自动重放。
    def dispatchable_runs(
        self, *, now: float | None = None, limit: int = 16
    ) -> list[str]:
        now = time.time() if now is None else float(now)
        rows = self.store.db.execute(
            "SELECT o.run_id FROM mental_model_refresh_occurrences o "
            "JOIN mental_model_refresh_policies p USING(model_id) "
            "WHERE o.state IN ('ADMITTED','RUNNING') AND p.enabled=1 AND p.retry_at<=? "
            "AND (o.owner_id IS NULL OR o.lease_until IS NULL OR o.lease_until<=?) "
            "ORDER BY o.created_at LIMIT ?",
            (now, now, max(1, min(int(limit), 128))),
        ).fetchall()
        return [str(row["run_id"]) for row in rows]

    # claim：同一 refresh occurrence 只允许一个活 owner；过期 lease 可被新 DurableExecutor 接管原 Run。
    def claim(
        self,
        run_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 8.0,
        now: float | None = None,
    ) -> bool:
        now = time.time() if now is None else float(now)
        ttl = max(2.0, min(float(ttl_seconds), 60.0))
        owner = str(owner_id or "").strip()
        if not owner or len(owner) > 300:
            raise ValueError("refresh owner_id is required")
        with self.store.tx() as db:
            row = db.execute(
                "SELECT state,owner_id,lease_until FROM mental_model_refresh_occurrences "
                "WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["state"] not in {"ADMITTED", "RUNNING"}:
                return False
            if (
                row["owner_id"]
                and row["owner_id"] != owner
                and row["lease_until"] is not None
                and float(row["lease_until"]) > now
            ):
                return False
            db.execute(
                "UPDATE mental_model_refresh_occurrences SET owner_id=?,lease_until=?,"
                "heartbeat_at=?,updated_at=? WHERE run_id=?",
                (owner, now + ttl, now, now, run_id),
            )
        return True

    # heartbeat：仅当前 owner 可续租；失败表示执行权已被收回，旧线程不得再发起新的模型工作。
    def heartbeat(
        self,
        run_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 8.0,
        now: float | None = None,
    ) -> bool:
        now = time.time() if now is None else float(now)
        ttl = max(2.0, min(float(ttl_seconds), 60.0))
        with self.store.tx() as db:
            changed = db.execute(
                "UPDATE mental_model_refresh_occurrences SET lease_until=?,heartbeat_at=?,"
                "updated_at=? WHERE run_id=? AND owner_id=? "
                "AND state IN ('ADMITTED','RUNNING')",
                (now + ttl, now, now, run_id, str(owner_id)),
            )
        return bool(changed.rowcount)

    # release：只释放自己的 lease；晚到旧 owner 不能清掉新 owner 的接管事实。
    def release(self, run_id: str, owner_id: str) -> None:
        with self.store.tx() as db:
            db.execute(
                "UPDATE mental_model_refresh_occurrences SET owner_id=NULL,lease_until=NULL "
                "WHERE run_id=? AND owner_id=?",
                (run_id, str(owner_id)),
            )

    # _request：把固定 sources 投影成一次性 synthesis 请求；模型只能返回 completion claim，不得到工具或执行权限。
    def _request(self, run_id: str, prepared: dict[str, Any], settings: dict[str, Any]) -> ModelRequest:
        sources = []
        for item in prepared["sources"]:
            sources.append(
                {
                    "memory_id": item["memory_id"],
                    "source_ref": item["source_ref"],
                    "revision": item["revision"],
                    "freshness": item["freshness"],
                    "text": item["text"],
                }
            )
        system = (
            "You synthesize one durable Mental Model from the supplied Memory evidence. "
            "Do not invent facts, do not cite information outside the supplied sources, and do not issue tool calls. "
            "Return request_completion only. Put the complete synthesized document in claim. "
            "Copy every source_ref you actually relied on into evidence_refs. Keep remaining empty."
        )
        user = canonical_json(
            {
                "mental_model": prepared["name"],
                "question": prepared["source_query"],
                "sources": sources,
                "rules": [
                    "preserve uncertainty and conflicts",
                    "prefer concise durable knowledge over conversational prose",
                    "no self-reference to the Mental Model",
                ],
            }
        )
        return ModelRequest(
            model=settings["model"],
            messages=(ModelMessage("system", system), ModelMessage("user", user)),
            response_schema=STEP_DECISION_SCHEMA,
            max_output_tokens=int(settings["max_output_tokens"]),
            thinking=settings.get("thinking"),
            num_ctx=settings.get("num_ctx"),
            temperature=float(settings.get("temperature") or 0.0),
            context_report=None,
        )

    # run：驱动一个 refresh occurrence；模型调用由 DecisionRuntime 记 Ticket/Receipt，发布前再次核对水位。
    def run(self, run_id: str, provider) -> dict[str, Any]:
        occurrence = self.occurrence(run_id)
        if occurrence["state"] == "SUCCEEDED":
            return occurrence
        if occurrence["state"] in {"FAILED","UNKNOWN","SUPERSEDED"}:
            return occurrence

        policy = self.policy(str(occurrence["model_id"]))
        settings = policy["settings"]
        if provider.provider_id != settings["provider"]:
            raise ValueError("provider differs from fixed refresh policy")

        prepared = self.views.prepare_refresh(
            str(occurrence["model_id"]), limit=12, resolution="L1"
        )
        if (
            int(prepared["model_revision"]) != int(occurrence["model_revision"])
            or int(prepared["observed_change_seq"]) != int(occurrence["source_change_seq"])
        ):
            with self.store.tx() as db:
                db.execute(
                    "UPDATE mental_model_refresh_occurrences SET state='SUPERSEDED',updated_at=?,"
                    "error='source changed before dispatch' WHERE run_id=?",
                    (time.time(), run_id),
                )
                self.store.transition_run(
                    run_id,
                    RunState.CANCELLED,
                    event_kind="MentalModelRefreshSuperseded",
                    payload={"model_id": occurrence["model_id"]},
                    _db=db,
                )
            return self.occurrence(run_id)

        with self.store.tx() as db:
            db.execute(
                "UPDATE mental_model_refresh_occurrences SET state='RUNNING',updated_at=? WHERE run_id=?",
                (time.time(), run_id),
            )

        try:
            _, decision = self.decisions.request_decision(
                run_id=run_id,
                provider=provider,
                model=settings["model"],
                max_output_tokens=int(settings["max_output_tokens"]),
                thinking=settings.get("thinking"),
                request_key=f"mental-model-refresh:{run_id}",
                model_request_override=self._request(run_id, prepared, settings),
            )
        except ProviderUnavailable:
            self.defer(str(occurrence["model_id"]), "provider unavailable before dispatch")
            with self.store.tx() as db:
                db.execute(
                    "UPDATE mental_model_refresh_occurrences SET state='ADMITTED',updated_at=?,error=? WHERE run_id=?",
                    (time.time(), "provider unavailable before dispatch", run_id),
                )
            return self.occurrence(run_id)
        except RecoveryRequired as exc:
            with self.store.tx() as db:
                db.execute(
                    "UPDATE mental_model_refresh_occurrences SET state='UNKNOWN',updated_at=?,error=? WHERE run_id=?",
                    (time.time(), str(exc)[:1000], run_id),
                )
                self.store.transition_run(
                    run_id,
                    RunState.RECOVERING,
                    event_kind="MentalModelRefreshUnknown",
                    payload={"reason": str(exc)[:500]},
                    _db=db,
                )
            return self.occurrence(run_id)
        except Exception as exc:
            # Ticket 后的未知异常由 DecisionRuntime 已转 UNKNOWN；已知解析/供应商失败则显式 FAILED。
            pending = self.store.db.execute(
                "SELECT 1 FROM model_invocations WHERE run_id=? AND state='UNKNOWN' LIMIT 1",
                (run_id,),
            ).fetchone()
            state = "UNKNOWN" if pending else "FAILED"
            with self.store.tx() as db:
                db.execute(
                    "UPDATE mental_model_refresh_occurrences SET state=?,updated_at=?,error=? WHERE run_id=?",
                    (state, time.time(), f"{type(exc).__name__}: {exc}"[:1000], run_id),
                )
                self.store.transition_run(
                    run_id,
                    RunState.RECOVERING if state == "UNKNOWN" else RunState.FAILED,
                    event_kind="MentalModelRefreshFailed",
                    payload={"state": state, "reason": f"{type(exc).__name__}: {exc}"[:500]},
                    _db=db,
                )
            if state == "FAILED":
                self.defer(str(occurrence["model_id"]), str(exc))
            return self.occurrence(run_id)

        if decision.decision_type != "request_completion" or decision.remaining:
            self.fail(run_id, "refresh model did not return a final synthesis")
            return self.occurrence(run_id)

        source_by_ref = {
            str(item["source_ref"]): str(item["memory_id"]) for item in prepared["sources"]
        }
        cited_ids = []
        for ref in decision.evidence_refs:
            memory_id = source_by_ref.get(str(ref))
            if memory_id and memory_id not in cited_ids:
                cited_ids.append(memory_id)
        if not cited_ids:
            self.fail(run_id, "refresh synthesis cited no admitted Memory evidence")
            return self.occurrence(run_id)

        try:
            self.views.commit_refresh(
                str(occurrence["model_id"]),
                content=str(decision.claim or ""),
                evidence_memory_ids=cited_ids,
                expected_model_revision=int(occurrence["model_revision"]),
                observed_change_seq=int(occurrence["source_change_seq"]),
            )
        except ValueError as exc:
            # 来源在模型调用期间变化是已知 race；旧 synthesis 不发布，标 SUPERSEDED 让下一水位另建机会。
            if "source scope changed" in str(exc) or "revision changed" in str(exc):
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE mental_model_refresh_occurrences SET state='SUPERSEDED',updated_at=?,error=? WHERE run_id=?",
                        (time.time(), str(exc)[:1000], run_id),
                    )
                    self.store.transition_run(
                        run_id,
                        RunState.CANCELLED,
                        event_kind="MentalModelRefreshSuperseded",
                        payload={"reason": str(exc)[:500]},
                        _db=db,
                    )
                return self.occurrence(run_id)
            self.fail(run_id, str(exc))
            return self.occurrence(run_id)

        with self.store.tx() as db:
            db.execute(
                "UPDATE mental_model_refresh_occurrences SET state='SUCCEEDED',updated_at=?,error=NULL WHERE run_id=?",
                (time.time(), run_id),
            )
            db.execute(
                "UPDATE mental_model_refresh_policies SET retry_at=0,retry_failures=0,"
                "last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE model_id=?",
                (occurrence["model_id"],),
            )
            self.store.transition_run(
                run_id,
                RunState.SUCCEEDED,
                event_kind="MentalModelRefreshCommitted",
                payload={
                    "model_id": occurrence["model_id"],
                    "evidence_count": len(cited_ids),
                },
                _db=db,
            )
        return self.occurrence(run_id)

    # fail：已知失败终止本 occurrence 并进入有界退避；不会覆盖已有 materialized content。
    def fail(self, run_id: str, reason: str) -> None:
        occurrence = self.occurrence(run_id)
        with self.store.tx() as db:
            db.execute(
                "UPDATE mental_model_refresh_occurrences SET state='FAILED',updated_at=?,error=? WHERE run_id=?",
                (time.time(), str(reason)[:1000], run_id),
            )
            self.store.transition_run(
                run_id,
                RunState.FAILED,
                event_kind="MentalModelRefreshFailed",
                payload={"state": "FAILED", "reason": str(reason)[:500]},
                _db=db,
            )
        self.defer(str(occurrence["model_id"]), reason)

    # defer：失败只推迟未来新水位机会；UNKNOWN occurrence 不会靠 retry_at 绕过原结果核对。
    def defer(self, model_id: str, reason: str) -> None:
        with self.store.tx() as db:
            row = db.execute(
                "SELECT retry_failures FROM mental_model_refresh_policies WHERE model_id=?",
                (model_id,),
            ).fetchone()
            if row is None:
                raise KeyError(model_id)
            failures = min(1_000_000, int(row["retry_failures"]) + 1)
            db.execute(
                "UPDATE mental_model_refresh_policies SET retry_failures=?,retry_at=?,last_error=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE model_id=?",
                (failures, time.time() + _retry_delay(failures), str(reason)[:1000], model_id),
            )
