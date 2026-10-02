"""Durable policy candidate/release control plane.

Promotion and rollback change only the policy pointer used by *future*
Workspace composition/admission. Existing Turn snapshots remain immutable.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain import canonical_json
from ..strategies.information_resolution import resolution_controller_from_config
from .calibration import build_calibration_matrix
from .cost_model import SqliteCostModelRegistry
from .evaluation_store import SqliteEvaluationLedger


SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_versions(
    policy_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    config_json TEXT NOT NULL,
    source_candidate_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS active_policies(
    domain TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policy_versions(policy_id),
    previous_policy_id TEXT REFERENCES policy_versions(policy_id),
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS policy_candidates(
    candidate_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    baseline_policy_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    changes_json TEXT NOT NULL,
    status TEXT NOT NULL,
    baseline_eval_run_id TEXT,
    candidate_eval_run_id TEXT,
    cost_model_id TEXT,
    calibration_json TEXT,
    decision_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS policy_history(
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    action TEXT NOT NULL,
    from_policy_id TEXT,
    to_policy_id TEXT NOT NULL,
    candidate_id TEXT,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SqliteEvolutionControl:
    BUILTIN_RESOLUTION_POLICY="resolution-rule-v1"

    def __init__(self,runtime):
        self.runtime=runtime
        self.store=runtime.store
        self.store.db.executescript(SCHEMA)
        self._ensure_builtin()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _ensure_builtin(self):
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO policy_versions(policy_id,domain,config_json,source_candidate_id) VALUES (?,?,?,NULL)",
                (
                    self.BUILTIN_RESOLUTION_POLICY,
                    "information_resolution",
                    canonical_json({"mode":"rule"}),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO active_policies(domain,policy_id,previous_policy_id,revision) VALUES (?,?,NULL,1)",
                ("information_resolution",self.BUILTIN_RESOLUTION_POLICY),
            )

    def active(self,domain: str = "information_resolution") -> dict[str,Any]:
        row=self.store.db.execute(
            "SELECT a.domain,a.policy_id,a.previous_policy_id,a.revision,a.updated_at,p.config_json "
            "FROM active_policies a JOIN policy_versions p ON p.policy_id=a.policy_id WHERE a.domain=?",
            (domain,),
        ).fetchone()
        if row is None:raise KeyError(domain)
        value=dict(row);value["config"]=json.loads(value.pop("config_json"))
        return value

    def policy(self,policy_id: str) -> dict[str,Any]:
        row=self.store.db.execute(
            "SELECT * FROM policy_versions WHERE policy_id=?",(policy_id,)
        ).fetchone()
        if row is None:raise KeyError(policy_id)
        value=dict(row);value["config"]=json.loads(value.pop("config_json"))
        return value

    def controller(self):
        return resolution_controller_from_config(self.active()["config"])

    def create_candidate(
        self,
        *,
        config: dict[str,Any],
        changes: list[str] | tuple[str,...],
        candidate_id: str | None = None,
        domain: str = "information_resolution",
    ) -> dict[str,Any]:
        if domain!="information_resolution":
            raise ValueError("v0.15 only admits information_resolution policy candidates")
        # Validate config by constructing the real policy before persistence.
        resolution_controller_from_config(config)
        changes=tuple(str(item).strip() for item in changes if str(item).strip())
        if not changes:raise ValueError("candidate requires at least one declared change")
        current=self.active(domain)
        cid=str(candidate_id or self._id("policy")).strip()
        if not cid or len(cid)>200:raise ValueError("candidate_id must contain 1-200 characters")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO policy_candidates(candidate_id,domain,baseline_policy_id,config_json,changes_json,status) "
                "VALUES (?,?,?,?,?,'DRAFT')",
                (cid,domain,current["policy_id"],canonical_json(config),canonical_json(changes)),
            )
        return self.candidate(cid)

    def candidate(self,candidate_id: str) -> dict[str,Any]:
        row=self.store.db.execute(
            "SELECT * FROM policy_candidates WHERE candidate_id=?",(candidate_id,)
        ).fetchone()
        if row is None:raise KeyError(candidate_id)
        value=dict(row)
        value["config"]=json.loads(value.pop("config_json"))
        value["changes"]=json.loads(value.pop("changes_json"))
        value["calibration"]=json.loads(value["calibration_json"]) if value.get("calibration_json") else None
        return value

    def candidates(self,limit: int = 100) -> list[dict[str,Any]]:
        return [
            self.candidate(row["candidate_id"])
            for row in self.store.db.execute(
                "SELECT candidate_id FROM policy_candidates ORDER BY rowid DESC LIMIT ?",
                (min(max(int(limit),1),200),),
            )
        ]

    def attach_evaluation(
        self,
        candidate_id: str,
        *,
        baseline_eval_run_id: str,
        candidate_eval_run_id: str,
        cost_model_id: str | None = None,
        min_pairs: int = 1,
    ) -> dict[str,Any]:
        candidate=self.candidate(candidate_id)
        if candidate["status"]=="PROMOTED":
            raise ValueError("promoted candidate evidence is immutable")
        ledger=SqliteEvaluationLedger(self.runtime)
        baseline=ledger.run(baseline_eval_run_id)
        tested=ledger.run(candidate_eval_run_id)
        if baseline["policy_id"]!=candidate["baseline_policy_id"]:
            raise ValueError("baseline eval policy does not match candidate baseline")
        if tested["policy_id"]!=candidate_id:
            raise ValueError("candidate eval policy_id must equal candidate_id")
        if baseline["suite_id"]!=tested["suite_id"] or baseline["suite_version"]!=tested["suite_version"]:
            raise ValueError("candidate and baseline must use the same suite/version")
        if not bool(baseline.get("complete_suite")) or not bool(tested.get("complete_suite")):
            raise ValueError("promotion evidence requires complete fixed-suite runs")
        if int(baseline.get("suite_case_count") or 0) != int(tested.get("suite_case_count") or 0):
            raise ValueError("baseline/candidate suite case counts differ")

        pairs=ledger.paired_comparisons(baseline_eval_run_id,candidate_eval_run_id)
        cost_model=SqliteCostModelRegistry(self.runtime).model(cost_model_id) if cost_model_id else None
        matrix=build_calibration_matrix(pairs,cost_model)
        calibration_ok,calibration_reason=matrix.promotion_gate(min_pairs=min_pairs)
        release_gate=tested["release_gate"]
        release_ok=bool(release_gate.get("passed"))
        eligible=release_ok and calibration_ok
        reason=(
            "candidate passed release and paired calibration gates"
            if eligible
            else "; ".join(
                part for part in (
                    None if release_ok else f"release gate: {release_gate.get('reason')}",
                    None if calibration_ok else f"calibration gate: {calibration_reason}",
                ) if part
            )
        )
        with self.store.tx() as db:
            db.execute(
                "UPDATE policy_candidates SET status=?,baseline_eval_run_id=?,candidate_eval_run_id=?,"
                "cost_model_id=?,calibration_json=?,decision_reason=?,updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                (
                    "ELIGIBLE" if eligible else "HOLD",
                    baseline_eval_run_id,candidate_eval_run_id,cost_model_id,
                    canonical_json(matrix.serializable()),reason,candidate_id,
                ),
            )
        return self.candidate(candidate_id)

    def promote(self,candidate_id: str) -> dict[str,Any]:
        candidate=self.candidate(candidate_id)
        if candidate["status"]!="ELIGIBLE":
            raise ValueError("only ELIGIBLE candidates can be promoted")
        current=self.active(candidate["domain"])
        if current["policy_id"]!=candidate["baseline_policy_id"]:
            raise ValueError("candidate baseline is stale; re-evaluate against current active policy")
        evidence={
            "baseline_eval_run_id":candidate["baseline_eval_run_id"],
            "candidate_eval_run_id":candidate["candidate_eval_run_id"],
            "cost_model_id":candidate["cost_model_id"],
            "calibration":candidate["calibration"],
        }
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO policy_versions(policy_id,domain,config_json,source_candidate_id) VALUES (?,?,?,?)",
                (candidate_id,candidate["domain"],canonical_json(candidate["config"]),candidate_id),
            )
            db.execute(
                "UPDATE active_policies SET previous_policy_id=policy_id,policy_id=?,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE domain=?",
                (candidate_id,candidate["domain"]),
            )
            db.execute(
                "UPDATE policy_candidates SET status='PROMOTED',decision_reason=?,updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                ("explicitly promoted after release + calibration gates",candidate_id),
            )
            db.execute(
                "INSERT INTO policy_history(domain,action,from_policy_id,to_policy_id,candidate_id,evidence_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    candidate["domain"],"PROMOTE",current["policy_id"],candidate_id,candidate_id,
                    canonical_json(evidence),
                ),
            )
        return self.status(candidate["domain"])

    def rollback(self,domain: str = "information_resolution", *, reason: str = "explicit rollback") -> dict[str,Any]:
        current=self.active(domain)
        previous=current.get("previous_policy_id")
        if not previous:raise ValueError("no previous policy is available for rollback")
        self.policy(previous)
        with self.store.tx() as db:
            db.execute(
                "UPDATE active_policies SET policy_id=?,previous_policy_id=?,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE domain=?",
                (previous,current["policy_id"],domain),
            )
            db.execute(
                "INSERT INTO policy_history(domain,action,from_policy_id,to_policy_id,candidate_id,evidence_json) "
                "VALUES (?,?,?,?,NULL,?)",
                (domain,"ROLLBACK",current["policy_id"],previous,canonical_json({"reason":reason})),
            )
        return self.status(domain)

    def history(self,domain: str = "information_resolution",limit: int = 50) -> list[dict[str,Any]]:
        return [
            {**dict(row),"evidence":json.loads(row["evidence_json"])}
            for row in self.store.db.execute(
                "SELECT * FROM policy_history WHERE domain=? ORDER BY history_id DESC LIMIT ?",
                (domain,min(max(int(limit),1),200)),
            )
        ]

    def status(self,domain: str = "information_resolution") -> dict[str,Any]:
        return {
            "active":self.active(domain),
            "history":self.history(domain,20),
        }
