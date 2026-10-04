"""候选、证据、活动策略与发布历史的 SQLite 所有者。
固定配置摘要，完整配对证据决定资格；Promote/Rollback 显式事务切换指针，不能修改正在运行 Turn 的快照。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain import canonical_json
from ..strategies.information_resolution import resolution_controller_from_config
from .calibration import build_calibration_matrix
from .cost_model import SqliteCostModelRegistry
from .evaluation import capability_efficiency_gate, eval_report_from_dict
from .evaluation_store import SqliteEvaluationLedger


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
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
    efficiency_gate_json TEXT,
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


# 候选、评测关联和活动指针的持久所有者；发布/回退必须显式且原子记录历史。
class SqliteEvolutionControl:
    # BUILTIN_RESOLUTION_POLICY：内置规则策略的稳定版本身份；启动补齐不得覆盖显式发布指针。
    BUILTIN_RESOLUTION_POLICY = "resolution-rule-v1"

    # 连接评测证据和活动策略表，幂等补齐内置基准；启动补齐不覆盖显式发布指针。
    def __init__(self, runtime):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        self.store.db.executescript(SCHEMA)
        columns = {
            row["name"]
            for row in self.store.db.execute("PRAGMA table_info(policy_candidates)")
        }
        if "efficiency_gate_json" not in columns:
            self.store.db.execute(
                "ALTER TABLE policy_candidates ADD COLUMN efficiency_gate_json TEXT"
            )
        self._ensure_builtin()

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # 幂等建立默认策略与活动指针；后续显式发布不被启动时默认值覆盖。
    def _ensure_builtin(self):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO policy_versions(policy_id,domain,config_json,source_candidate_id) VALUES (?,?,?,NULL)",
                (
                    self.BUILTIN_RESOLUTION_POLICY,
                    "information_resolution",
                    canonical_json({"mode": "rule"}),
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO active_policies(domain,policy_id,previous_policy_id,revision) VALUES (?,?,NULL,1)",
                ("information_resolution", self.BUILTIN_RESOLUTION_POLICY),
            )

    # 读取某策略的持久活动 policy；Workspace 仅在新 Turn 装配时读取。
    def active(self, domain: str = "information_resolution") -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT a.domain,a.policy_id,a.previous_policy_id,a.revision,a.updated_at,p.config_json "
            "FROM active_policies a JOIN policy_versions p ON p.policy_id=a.policy_id WHERE a.domain=?",
            (domain,),
        ).fetchone()
        if row is None:
            raise KeyError(domain)
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        return value

    # 读取固定 policy 配置和身份；已准入 Turn 不随活动指针变化。
    def policy(self, policy_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM policy_versions WHERE policy_id=?", (policy_id,)
        ).fetchone()
        if row is None:
            raise KeyError(policy_id)
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        return value

    # 从明确 policy 配置装配纯 ResolutionController；无供应商或执行副作用。
    def controller(self):
        return resolution_controller_from_config(self.active()["config"])

    # 冻结候选配置摘要、baseline 和声明变更；不立即影响生产路由。
    def create_candidate(
        self,
        *,
        config: dict[str, Any],
        changes: list[str] | tuple[str, ...],
        candidate_id: str | None = None,
        domain: str = "information_resolution",
    ) -> dict[str, Any]:
        if domain != "information_resolution":
            raise ValueError(
                "v0.15 only admits information_resolution policy candidates"
            )
        # 持久化前装配实际纯策略进行配置校验，拒绝无法装配的候选。
        resolution_controller_from_config(config)
        changes = tuple(str(item).strip() for item in changes if str(item).strip())
        if not changes:
            raise ValueError("candidate requires at least one declared change")
        current = self.active(domain)
        cid = str(candidate_id or self._id("policy")).strip()
        if not cid or len(cid) > 200:
            raise ValueError("candidate_id must contain 1-200 characters")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO policy_candidates(candidate_id,domain,baseline_policy_id,config_json,changes_json,status) "
                "VALUES (?,?,?,?,?,'DRAFT')",
                (
                    cid,
                    domain,
                    current["policy_id"],
                    canonical_json(config),
                    canonical_json(changes),
                ),
            )
        return self.candidate(cid)

    # 读取候选及固定证据关联；缺失身份拒绝，不按当前全局配置补造候选。
    def candidate(self, candidate_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM policy_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        value = dict(row)
        value["config"] = json.loads(value.pop("config_json"))
        value["changes"] = json.loads(value.pop("changes_json"))
        value["calibration"] = (
            json.loads(value["calibration_json"])
            if value.get("calibration_json")
            else None
        )
        value["efficiency_gate"] = (
            json.loads(value["efficiency_gate_json"])
            if value.get("efficiency_gate_json")
            else None
        )
        return value

    # 列出候选研究状态；列表不触发发布。
    def candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            self.candidate(row["candidate_id"])
            for row in self.store.db.execute(
                "SELECT candidate_id FROM policy_candidates ORDER BY rowid DESC LIMIT ?",
                (min(max(int(limit), 1), 200),),
            )
        ]

    # 要求 baseline/candidate 的固定完整集身份与策略相符，再保存发布证据和资格。
    def attach_evaluation(
        self,
        candidate_id: str,
        *,
        baseline_eval_run_id: str,
        candidate_eval_run_id: str,
        cost_model_id: str | None = None,
        min_pairs: int = 1,
    ) -> dict[str, Any]:
        candidate = self.candidate(candidate_id)
        if candidate["status"] == "PROMOTED":
            raise ValueError("promoted candidate evidence is immutable")
        ledger = SqliteEvaluationLedger(self.runtime)
        baseline = ledger.run(baseline_eval_run_id)
        tested = ledger.run(candidate_eval_run_id)
        if baseline["policy_id"] != candidate["baseline_policy_id"]:
            raise ValueError("baseline eval policy does not match candidate baseline")
        if tested["policy_id"] != candidate_id:
            raise ValueError("candidate eval policy_id must equal candidate_id")
        if (
            baseline["suite_id"] != tested["suite_id"]
            or baseline["suite_version"] != tested["suite_version"]
        ):
            raise ValueError("candidate and baseline must use the same suite/version")
        if not bool(baseline.get("complete_suite")) or not bool(
            tested.get("complete_suite")
        ):
            raise ValueError("promotion evidence requires complete fixed-suite runs")
        if int(baseline.get("suite_case_count") or 0) != int(
            tested.get("suite_case_count") or 0
        ):
            raise ValueError("baseline/candidate suite case counts differ")

        pairs = ledger.paired_comparisons(baseline_eval_run_id, candidate_eval_run_id)
        cost_model = (
            SqliteCostModelRegistry(self.runtime).model(cost_model_id)
            if cost_model_id
            else None
        )
        matrix = build_calibration_matrix(pairs, cost_model)
        calibration_ok, calibration_reason = matrix.promotion_gate(min_pairs=min_pairs)
        release_gate = tested["release_gate"]
        release_ok = bool(release_gate.get("passed"))
        efficiency_ok, efficiency_reason, cost_delta = capability_efficiency_gate(
            eval_report_from_dict(baseline["report"]),
            eval_report_from_dict(tested["report"]),
            pairs,
            require_improvement=False,
        )
        efficiency_gate = {
            "passed": efficiency_ok,
            "reason": efficiency_reason,
            "cost_delta": cost_delta,
        }
        eligible = release_ok and calibration_ok and efficiency_ok
        reason = (
            "candidate passed release, capability/efficiency, and paired calibration gates"
            if eligible
            else "; ".join(
                part
                for part in (
                    (
                        None
                        if release_ok
                        else f"release gate: {release_gate.get('reason')}"
                    ),
                    (
                        None
                        if efficiency_ok
                        else f"capability/efficiency gate: {efficiency_reason}"
                    ),
                    (
                        None
                        if calibration_ok
                        else f"calibration gate: {calibration_reason}"
                    ),
                )
                if part
            )
        )
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            # 评测计算期间可能已经发布；写锁内复核，不能改写已发布候选的证据。
            if self.candidate(candidate_id)["status"] == "PROMOTED":
                raise ValueError("promoted candidate evidence is immutable")
            db.execute(
                "UPDATE policy_candidates SET status=?,baseline_eval_run_id=?,candidate_eval_run_id=?,"
                "cost_model_id=?,calibration_json=?,efficiency_gate_json=?,decision_reason=?,updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                (
                    "ELIGIBLE" if eligible else "HOLD",
                    baseline_eval_run_id,
                    candidate_eval_run_id,
                    cost_model_id,
                    canonical_json(matrix.serializable()),
                    canonical_json(efficiency_gate),
                    reason,
                    candidate_id,
                ),
            )
        return self.candidate(candidate_id)

    # 显式校验候选资格和 baseline 活动身份，同事务切换指针并记历史。
    def promote(self, candidate_id: str) -> dict[str, Any]:
        # 候选资格与 baseline 必须在 BEGIN IMMEDIATE 后核对；事务前的检查会被另一发布者穿透。
        with self.store.tx() as db:
            candidate = self.candidate(candidate_id)
            if candidate["status"] != "ELIGIBLE":
                raise ValueError("only ELIGIBLE candidates can be promoted")
            current = self.active(candidate["domain"])
            if current["policy_id"] != candidate["baseline_policy_id"]:
                raise ValueError("candidate baseline is stale; re-evaluate against current active policy")
            evidence = {
                "baseline_eval_run_id": candidate["baseline_eval_run_id"],
                "candidate_eval_run_id": candidate["candidate_eval_run_id"],
                "cost_model_id": candidate["cost_model_id"],
                "calibration": candidate["calibration"],
                "efficiency_gate": candidate["efficiency_gate"],
            }
            db.execute(
                "INSERT OR IGNORE INTO policy_versions(policy_id,domain,config_json,source_candidate_id) VALUES (?,?,?,?)",
                (
                    candidate_id,
                    candidate["domain"],
                    canonical_json(candidate["config"]),
                    candidate_id,
                ),
            )
            db.execute(
                "UPDATE active_policies SET previous_policy_id=policy_id,policy_id=?,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE domain=?",
                (candidate_id, candidate["domain"]),
            )
            db.execute(
                "UPDATE policy_candidates SET status='PROMOTED',decision_reason=?,updated_at=CURRENT_TIMESTAMP WHERE candidate_id=?",
                (
                    "explicitly promoted after release + capability/efficiency + calibration gates",
                    candidate_id,
                ),
            )
            db.execute(
                "INSERT INTO policy_history(domain,action,from_policy_id,to_policy_id,candidate_id,evidence_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    candidate["domain"],
                    "PROMOTE",
                    current["policy_id"],
                    candidate_id,
                    candidate_id,
                    canonical_json(evidence),
                ),
            )
        return self.status(candidate["domain"])

    # 显式按历史有效版本同事务恢复活动策略并记操作；未来 Turn 才读取新指针。
    def rollback(
        self,
        domain: str = "information_resolution",
        *,
        reason: str = "explicit rollback",
    ) -> dict[str, Any]:
        # 回退目标也在同一个写事务内读取；迟到请求不能把更新后的指针覆盖为旧快照。
        with self.store.tx() as db:
            current = self.active(domain)
            previous = current.get("previous_policy_id")
            if not previous:
                raise ValueError("no previous policy is available for rollback")
            self.policy(previous)
            db.execute(
                "UPDATE active_policies SET policy_id=?,previous_policy_id=?,revision=revision+1,"
                "updated_at=CURRENT_TIMESTAMP WHERE domain=?",
                (previous, current["policy_id"], domain),
            )
            db.execute(
                "INSERT INTO policy_history(domain,action,from_policy_id,to_policy_id,candidate_id,evidence_json) "
                "VALUES (?,?,?,?,NULL,?)",
                (
                    domain,
                    "ROLLBACK",
                    current["policy_id"],
                    previous,
                    canonical_json({"reason": reason}),
                ),
            )
        return self.status(domain)

    # 读取某策略有界发布/回退历史；用于审计，不改历史 Turn。
    def history(
        self, domain: str = "information_resolution", limit: int = 50
    ) -> list[dict[str, Any]]:
        return [
            {**dict(row), "evidence": json.loads(row["evidence_json"])}
            for row in self.store.db.execute(
                "SELECT * FROM policy_history WHERE domain=? ORDER BY history_id DESC LIMIT ?",
                (domain, min(max(int(limit), 1), 200)),
            )
        ]

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, domain: str = "information_resolution") -> dict[str, Any]:
        return {
            "active": self.active(domain),
            "history": self.history(domain, 20),
        }
