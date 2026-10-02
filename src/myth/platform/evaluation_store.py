"""Durable local ledger for evaluation evidence and policy comparisons."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain import canonical_json
from .evaluation import EvalObservation, EvalVerdict, compare_observations


SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_runs(
    eval_run_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL,
    suite_version INTEGER NOT NULL,
    policy_id TEXT NOT NULL,
    report_json TEXT NOT NULL,
    release_gate_json TEXT NOT NULL,
    elapsed_ms REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evaluation_observations(
    eval_run_id TEXT NOT NULL REFERENCES evaluation_runs(eval_run_id),
    case_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    safety_regression INTEGER NOT NULL DEFAULT 0,
    comparison_key TEXT,
    PRIMARY KEY(eval_run_id, case_id)
);
"""


class SqliteEvaluationLedger:
    def __init__(self, runtime):
        self.runtime=runtime
        self.store=runtime.store
        self.store.db.executescript(SCHEMA)

    @staticmethod
    def _id() -> str:
        return f"eval_{uuid.uuid4().hex}"

    def record(self, result: dict[str, Any], *, policy_id: str) -> dict[str, Any]:
        policy=str(policy_id or "").strip()
        if not policy or len(policy)>200:
            raise ValueError("policy_id must contain 1-200 characters")
        result_policy=str(result.get("policy_id") or policy).strip()
        if result_policy != policy:
            raise ValueError("recorded policy_id must match the runner result")
        suite_id=str(result.get("suite_id") or "").strip()
        suite_version=int(result.get("version") or 0)
        if not suite_id or suite_version<1:
            raise ValueError("evaluation result requires suite id/version")
        observations=result.get("observations") or []
        if not isinstance(observations,list):
            raise ValueError("evaluation observations must be a list")
        eval_run_id=self._id()
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO evaluation_runs(eval_run_id,suite_id,suite_version,policy_id,report_json,release_gate_json,elapsed_ms) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    eval_run_id,
                    suite_id,
                    suite_version,
                    policy,
                    canonical_json(result.get("report") or {}),
                    canonical_json(result.get("release_gate") or {}),
                    float(result.get("elapsed_ms") or 0.0),
                ),
            )
            for item in observations:
                db.execute(
                    "INSERT INTO evaluation_observations("
                    "eval_run_id,case_id,verdict,reason,metrics_json,evidence_refs_json,safety_regression,comparison_key"
                    ") VALUES (?,?,?,?,?,?,?,?)",
                    (
                        eval_run_id,
                        str(item.get("case_id") or ""),
                        str(item.get("verdict") or ""),
                        str(item.get("reason") or ""),
                        canonical_json(item.get("metrics") or {}),
                        canonical_json(item.get("evidence_refs") or []),
                        int(bool(item.get("safety_regression",False))),
                        item.get("comparison_key") or item.get("case_id"),
                    ),
                )
        return self.run(eval_run_id)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1<=limit<=200:
            raise ValueError("limit must be 1-200")
        return [
            {
                **dict(row),
                "report":json.loads(row["report_json"]),
                "release_gate":json.loads(row["release_gate_json"]),
            }
            for row in self.store.db.execute(
                "SELECT * FROM evaluation_runs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
        ]

    def run(self, eval_run_id: str) -> dict[str, Any]:
        row=self.store.db.execute(
            "SELECT * FROM evaluation_runs WHERE eval_run_id=?",
            (eval_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(eval_run_id)
        observations=[
            {
                **dict(item),
                "metrics":json.loads(item["metrics_json"]),
                "evidence_refs":json.loads(item["evidence_refs_json"]),
                "safety_regression":bool(item["safety_regression"]),
            }
            for item in self.store.db.execute(
                "SELECT * FROM evaluation_observations WHERE eval_run_id=? ORDER BY case_id",
                (eval_run_id,),
            )
        ]
        return {
            **dict(row),
            "report":json.loads(row["report_json"]),
            "release_gate":json.loads(row["release_gate_json"]),
            "observations":observations,
        }

    @staticmethod
    def _observation(row: dict[str, Any], policy_id: str) -> EvalObservation:
        return EvalObservation(
            case_id=row["case_id"],
            verdict=EvalVerdict(row["verdict"]),
            reason=row["reason"],
            metrics=dict(row.get("metrics") or {}),
            evidence_refs=tuple(row.get("evidence_refs") or ()),
            safety_regression=bool(row.get("safety_regression")),
            policy_id=policy_id,
            comparison_key=row.get("comparison_key") or row["case_id"],
        )

    def paired_comparisons(self, baseline_eval_run_id: str, candidate_eval_run_id: str):
        baseline=self.run(baseline_eval_run_id)
        candidate=self.run(candidate_eval_run_id)
        if baseline["suite_id"] != candidate["suite_id"] or baseline["suite_version"] != candidate["suite_version"]:
            raise ValueError("policy comparison requires the same suite id/version")
        before={item["case_id"]:item for item in baseline["observations"]}
        after={item["case_id"]:item for item in candidate["observations"]}
        pairs=[]
        for case_id in sorted(set(before) & set(after)):
            pairs.append(compare_observations(
                self._observation(before[case_id],baseline["policy_id"]),
                self._observation(after[case_id],candidate["policy_id"]),
            ))
        return pairs

    def compare(self, baseline_eval_run_id: str, candidate_eval_run_id: str) -> list[dict[str, Any]]:
        rows=[]
        for comparison in self.paired_comparisons(baseline_eval_run_id,candidate_eval_run_id):
            rows.append({
                "case_id":comparison.case_id,
                "comparison_key":comparison.comparison_key,
                "baseline_policy_id":comparison.baseline_policy_id,
                "candidate_policy_id":comparison.candidate_policy_id,
                "baseline_verdict":comparison.baseline_verdict.value,
                "candidate_verdict":comparison.candidate_verdict.value,
                "observed_quality_gain":comparison.observed_quality_gain,
                "cost_delta":comparison.cost_delta,
                "evidence_refs":list(comparison.evidence_refs),
                "calibrated":comparison.calibrated,
            })
        return rows

