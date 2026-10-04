"""评测运行和逐题观测的 SQLite 证据账本。
固定 suite/version/policy 身份保存观测；对比使用同题配对，筛选或缺项不能作为完整发布证明。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain import canonical_json
from .evaluation import EvalObservation, EvalVerdict, attribution_matrix, compare_observations


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_runs(
    eval_run_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL,
    suite_version INTEGER NOT NULL,
    policy_id TEXT NOT NULL,
    report_json TEXT NOT NULL,
    release_gate_json TEXT NOT NULL,
    elapsed_ms REAL,
    suite_case_count INTEGER,
    selected_case_count INTEGER,
    complete_suite INTEGER NOT NULL DEFAULT 0,
    evaluation_partition TEXT NOT NULL DEFAULT 'final',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evaluation_observations(
    eval_run_id TEXT NOT NULL REFERENCES evaluation_runs(eval_run_id),
    case_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    mechanism_events_json TEXT NOT NULL DEFAULT '[]',
    safety_regression INTEGER NOT NULL DEFAULT 0,
    comparison_key TEXT,
    PRIMARY KEY(eval_run_id, case_id)
);
"""


# 固定评测及逐题证据的持久目录；配对身份包含 suite/version/case，报告不是自动发布命令。
class SqliteEvaluationLedger:
    # 复用 Runtime 连接建立固定评测报告/逐题观测表；不执行生产任务或自动发布策略。
    def __init__(self, runtime):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        self.store.db.executescript(SCHEMA)
        columns = {
            row["name"]
            for row in self.store.db.execute("PRAGMA table_info(evaluation_runs)")
        }
        for name, ddl in (
            ("suite_case_count", "INTEGER"),
            ("selected_case_count", "INTEGER"),
            ("complete_suite", "INTEGER NOT NULL DEFAULT 0"),
            ("evaluation_partition", "TEXT NOT NULL DEFAULT 'final'"),
        ):
            if name not in columns:
                self.store.db.execute(
                    f"ALTER TABLE evaluation_runs ADD COLUMN {name} {ddl}"
                )
        observation_columns = {
            row["name"]
            for row in self.store.db.execute("PRAGMA table_info(evaluation_observations)")
        }
        if "mechanism_events_json" not in observation_columns:
            self.store.db.execute(
                "ALTER TABLE evaluation_observations ADD COLUMN mechanism_events_json TEXT NOT NULL DEFAULT '[]'"
            )

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id() -> str:
        return f"eval_{uuid.uuid4().hex}"

    # 同事务登记固定报告和逐题观测，保留 policy 与完整覆盖身份。
    def record(self, result: dict[str, Any], *, policy_id: str) -> dict[str, Any]:
        policy = str(policy_id or "").strip()
        if not policy or len(policy) > 200:
            raise ValueError("policy_id must contain 1-200 characters")
        result_policy = str(result.get("policy_id") or policy).strip()
        if result_policy != policy:
            raise ValueError("recorded policy_id must match the runner result")
        suite_id = str(result.get("suite_id") or "").strip()
        suite_version = int(result.get("version") or 0)
        if not suite_id or suite_version < 1:
            raise ValueError("evaluation result requires suite id/version")
        observations = result.get("observations") or []
        partition = str(result.get("evaluation_partition") or "final").strip().lower()
        if partition not in {"discovery", "final"}:
            raise ValueError("evaluation_partition must be discovery or final")
        if not isinstance(observations, list):
            raise ValueError("evaluation observations must be a list")
        eval_run_id = self._id()
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO evaluation_runs(eval_run_id,suite_id,suite_version,policy_id,report_json,release_gate_json,elapsed_ms,"
                "suite_case_count,selected_case_count,complete_suite,evaluation_partition) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eval_run_id,
                    suite_id,
                    suite_version,
                    policy,
                    canonical_json(result.get("report") or {}),
                    canonical_json(result.get("release_gate") or {}),
                    float(result.get("elapsed_ms") or 0.0),
                    int(result.get("suite_case_count") or len(observations)),
                    int(result.get("selected_case_count") or len(observations)),
                    int(bool(result.get("complete_suite", False))),
                    partition,
                ),
            )
            for item in observations:
                db.execute(
                    "INSERT INTO evaluation_observations("
                    "eval_run_id,case_id,verdict,reason,metrics_json,evidence_refs_json,mechanism_events_json,safety_regression,comparison_key"
                    ") VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        eval_run_id,
                        str(item.get("case_id") or ""),
                        str(item.get("verdict") or ""),
                        str(item.get("reason") or ""),
                        canonical_json(item.get("metrics") or {}),
                        canonical_json(item.get("evidence_refs") or []),
                        canonical_json(item.get("mechanism_events") or []),
                        int(bool(item.get("safety_regression", False))),
                        item.get("comparison_key") or item.get("case_id"),
                    ),
                )
        return self.run(eval_run_id)

    # 读取有界 Run 列表供产品/CLI 展示；这是历史投影，不重新驱动任何 Run。
    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be 1-200")
        return [
            {
                **dict(row),
                "report": json.loads(row["report_json"]),
                "release_gate": json.loads(row["release_gate_json"]),
            }
            for row in self.store.db.execute(
                "SELECT * FROM evaluation_runs ORDER BY rowid DESC LIMIT ?",
                (limit,),
            )
        ]

    # 按 eval_run_id 读取持久报告与逐题证据；此方法是查询，不驱动业务 Run。
    def run(self, eval_run_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM evaluation_runs WHERE eval_run_id=?",
            (eval_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(eval_run_id)
        observations = [
            {
                **dict(item),
                "metrics": json.loads(item["metrics_json"]),
                "evidence_refs": json.loads(item["evidence_refs_json"]),
                "mechanism_events": json.loads(item["mechanism_events_json"]),
                "safety_regression": bool(item["safety_regression"]),
            }
            for item in self.store.db.execute(
                "SELECT * FROM evaluation_observations WHERE eval_run_id=? ORDER BY case_id",
                (eval_run_id,),
            )
        ]
        return {
            **dict(row),
            "report": json.loads(row["report_json"]),
            "release_gate": json.loads(row["release_gate_json"]),
            "observations": observations,
        }

    # 还原一条持久观测的字段/引用；不重新运行或修改预期。
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
            mechanism_events=tuple(row.get("mechanism_events") or ()),
        )

    # 要求两个 run 的 suite/version 完全一致再按同题配对；不能跨版本比较刷分。
    def paired_comparisons(self, baseline_eval_run_id: str, candidate_eval_run_id: str):
        baseline = self.run(baseline_eval_run_id)
        candidate = self.run(candidate_eval_run_id)
        if (
            baseline["suite_id"] != candidate["suite_id"]
            or baseline["suite_version"] != candidate["suite_version"]
        ):
            raise ValueError("policy comparison requires the same suite id/version")
        before = {item["case_id"]: item for item in baseline["observations"]}
        after = {item["case_id"]: item for item in candidate["observations"]}
        pairs = []
        for case_id in sorted(set(before) & set(after)):
            pairs.append(
                compare_observations(
                    self._observation(before[case_id], baseline["policy_id"]),
                    self._observation(after[case_id], candidate["policy_id"]),
                )
            )
        return pairs

    # 最终评测题不得与同一候选策略已经用于 discovery 的题重叠；否则 final 已经泄漏给搜索过程。
    def require_held_out_final(self, eval_run_id: str) -> None:
        final = self.run(eval_run_id)
        if final.get("evaluation_partition") != "final":
            raise ValueError("promotion evidence must use final evaluation partition")
        final_cases = {item["case_id"] for item in final["observations"]}
        discovery_cases = {
            row["case_id"]
            for row in self.store.db.execute(
                "SELECT o.case_id FROM evaluation_observations o "
                "JOIN evaluation_runs r USING(eval_run_id) "
                "WHERE r.policy_id=? AND r.evaluation_partition='discovery'",
                (final["policy_id"],),
            ).fetchall()
        }
        overlap = final_cases & discovery_cases
        if overlap:
            raise ValueError(
                "held-out final cases were already used in discovery: "
                + ",".join(sorted(overlap))
            )

    # 基于完整配对结果汇总质量/成本与发布判断；保留逐题回归和缺证据。
    def compare(
        self, baseline_eval_run_id: str, candidate_eval_run_id: str
    ) -> list[dict[str, Any]]:
        rows = []
        for comparison in self.paired_comparisons(
            baseline_eval_run_id, candidate_eval_run_id
        ):
            rows.append(
                {
                    "case_id": comparison.case_id,
                    "comparison_key": comparison.comparison_key,
                    "baseline_policy_id": comparison.baseline_policy_id,
                    "candidate_policy_id": comparison.candidate_policy_id,
                    "baseline_verdict": comparison.baseline_verdict.value,
                    "candidate_verdict": comparison.candidate_verdict.value,
                    "observed_quality_gain": comparison.observed_quality_gain,
                    "cost_delta": comparison.cost_delta,
                    "evidence_refs": list(comparison.evidence_refs),
                    "calibrated": comparison.calibrated,
                }
            )
        return rows


    # 从持久逐题观测生成 task×policy outcome flip 与实际机制线索；相关性仍不等于因果。
    def attribution(
        self, baseline_eval_run_id: str, candidate_eval_run_id: str
    ) -> dict[str, object]:
        baseline = self.run(baseline_eval_run_id)
        candidate = self.run(candidate_eval_run_id)
        if (
            baseline["suite_id"] != candidate["suite_id"]
            or baseline["suite_version"] != candidate["suite_version"]
        ):
            raise ValueError("policy attribution requires the same suite id/version")
        observations = tuple(
            self._observation(item, baseline["policy_id"])
            for item in baseline["observations"]
        ) + tuple(
            self._observation(item, candidate["policy_id"])
            for item in candidate["observations"]
        )
        return attribution_matrix(
            observations,
            baseline_policy_id=baseline["policy_id"],
        )
