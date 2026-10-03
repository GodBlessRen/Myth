"""Core 执行事实与多资源预算的 SQLite 状态所有者。
短写事务原子提交身份、预留、Ticket、Receipt 和事件；外部 I/O 由 Runtime 协调，UNKNOWN 占用不能当作零消耗释放。"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from .domain import (
    AttemptState,
    BudgetExceeded,
    IdentityConflict,
    InvalidTransition,
    Outcome,
    ReceiptData,
    RunState,
    Verdict,
    canonical_json,
)


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
# runs 固定入口摘要、验收版本与控制修订；next_sequence 为本 Run 事件序号，不是全库顺序。
# accounts 的 limit_units/reserved/settled/unknown_held 均沿用 meter 单位：调用次数、字节或 Token。
# reservations 绑定 Attempt 的各资源；效果已知、用量未知时只转移占用，不能按零释放。
# actions 固定前后字节/请求摘要；attempts 是机会，tickets 是授权，receipts 是效果事实，三者不能合并。
# verification_reports 只对 candidate_digest/acceptance_version 生效；deliveries 必须引用对应 PASS 报告。
SCHEMA = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY NOT NULL,
    request_id TEXT NOT NULL UNIQUE,
    entry_digest TEXT NOT NULL,
    goal TEXT NOT NULL,
    acceptance_version TEXT NOT NULL,
    state TEXT NOT NULL,
    control_revision INTEGER NOT NULL DEFAULT 1,
    next_sequence INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    kind TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    target_name TEXT NOT NULL,
    before_digest TEXT NOT NULL,
    after_digest TEXT NOT NULL,
    old_text TEXT NOT NULL,
    new_text TEXT NOT NULL,
    expected_count INTEGER NOT NULL CHECK(expected_count > 0),
    UNIQUE(action_id, run_id)
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY NOT NULL,
    action_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(attempt_no > 0),
    state TEXT NOT NULL,
    envelope_digest TEXT NOT NULL,
    outcome TEXT,
    last_error TEXT,
    UNIQUE(action_id, attempt_no),
    UNIQUE(attempt_id, run_id),
    UNIQUE(attempt_id, envelope_digest),
    FOREIGN KEY(action_id, run_id) REFERENCES actions(action_id, run_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE,
    envelope_digest TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(attempt_id, envelope_digest)
        REFERENCES attempts(attempt_id, envelope_digest)
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY NOT NULL,
    attempt_id TEXT NOT NULL,
    envelope_digest TEXT NOT NULL,
    outcome TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    usage_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(attempt_id, envelope_digest)
        REFERENCES attempts(attempt_id, envelope_digest)
);

CREATE TABLE IF NOT EXISTS accounts (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    meter TEXT NOT NULL,
    limit_units INTEGER NOT NULL CHECK(limit_units >= 0),
    settled INTEGER NOT NULL DEFAULT 0 CHECK(settled >= 0),
    reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved >= 0),
    unknown_held INTEGER NOT NULL DEFAULT 0 CHECK(unknown_held >= 0),
    PRIMARY KEY(run_id, meter)
);

CREATE TABLE IF NOT EXISTS reservations (
    attempt_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    meter TEXT NOT NULL,
    reserved_amount INTEGER NOT NULL CHECK(reserved_amount >= 0),
    settled_amount INTEGER NOT NULL DEFAULT 0 CHECK(settled_amount >= 0),
    unknown_amount INTEGER NOT NULL DEFAULT 0 CHECK(unknown_amount >= 0),
    closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)),
    PRIMARY KEY(attempt_id, meter),
    FOREIGN KEY(attempt_id, run_id) REFERENCES attempts(attempt_id, run_id),
    FOREIGN KEY(run_id, meter) REFERENCES accounts(run_id, meter)
);

CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(run_id, sequence)
);

CREATE TABLE IF NOT EXISTS verification_reports (
    report_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    action_id TEXT NOT NULL REFERENCES actions(action_id),
    candidate_digest TEXT NOT NULL,
    acceptance_version TEXT NOT NULL,
    verdict TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    action_id TEXT NOT NULL REFERENCES actions(action_id),
    candidate_digest TEXT NOT NULL,
    report_id TEXT NOT NULL REFERENCES verification_reports(report_id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS agent_tool_bindings (
    decision_id TEXT PRIMARY KEY NOT NULL,
    action_id TEXT UNIQUE NOT NULL REFERENCES actions(action_id)
);
"""


class RuntimeStore:
    """每实例一条 SQLite 连接；短事务串行化本地写入，禁止隐式嵌套，调用方负责外部效果与恢复协调。"""

    # 打开本线程 SQLite 连接，启用外键/WAL/FULL 同步与五秒写锁等待，再幂等建立 Core 表；调用方负责 close。
    def __init__(self, path: Path) -> None:
        # path：本对象持久文件路径；数据身份由所属合同另行校验。
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # db：本实例 SQLite 连接；事务身份必须一致，不能跨线程或跨连接冒充原子提交。
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self.db.executescript(SCHEMA)

    # 关闭本实例持有的连接/资源；持久 Run 和收据生命周期继续保留。
    def close(self) -> None:
        self.db.close()

    # BEGIN IMMEDIATE 串行化写入，成功提交、任何 BaseException 回滚；禁止嵌套及外部效果塞进事务。
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        if self.db.in_transaction:
            raise RuntimeError("nested store transactions are not allowed")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    # 将 SQLite 行转为普通数据副本；应用不获得游标或写权限。
    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else dict(row)

    # 在调用方事务内分配 Run 顺序号并记录事件；顺序分配和事件不可部分提交。
    def _event(
        self, db: sqlite3.Connection, run_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        row = db.execute(
            "SELECT next_sequence FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        seq = int(row[0])
        db.execute(
            "UPDATE runs SET next_sequence=next_sequence+1 WHERE run_id=?", (run_id,)
        )
        db.execute(
            "INSERT INTO events(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
            (run_id, seq, kind, canonical_json(payload)),
        )

    # 按固定入口身份查询已有 Run；事务外可提前避免重复基线准备，最终去重仍须在写事务内再核对。
    def request_run(self, request_id: str, entry_digest: str) -> str | None:
        existing = self.db.execute(
            "SELECT run_id,entry_digest FROM runs WHERE request_id=?", (request_id,)
        ).fetchone()
        if existing is None:
            return None
        if existing["entry_digest"] != entry_digest:
            raise IdentityConflict("request_id reused with different request content")
        return str(existing["run_id"])

    # 开始独立短事务或加入本连接的明确准入事务；禁止跨连接/无事务传入，绝不隐式嵌套。
    def admission_transaction(self, db: sqlite3.Connection | None = None):
        if db is not None:
            if db is not self.db or not db.in_transaction:
                raise RuntimeError("admission requires this store's active transaction")
            return nullcontext(db)
        return self.tx()

    # 同事务固定 request_id/entry_digest、Run、所有预算和首事件；_db 允许入口把初始 Intent 一起提交。
    def create_run(
        self,
        *,
        run_id: str,
        request_id: str,
        entry_digest: str,
        goal: str,
        acceptance_version: str,
        budgets: dict[str, int],
        _db: sqlite3.Connection | None = None,
    ) -> tuple[str, bool]:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.admission_transaction(_db) as db:
            existing = self.request_run(request_id, entry_digest)
            if existing is not None:
                return existing, False

            db.execute(
                "INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) "
                "VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    request_id,
                    entry_digest,
                    goal,
                    acceptance_version,
                    RunState.RUNNING.value,
                ),
            )
            for meter, limit in sorted(budgets.items()):
                if not meter or type(limit) is not int or limit < 0:
                    raise ValueError(
                        "budget meters require non-empty names and non-negative integer limits"
                    )
                db.execute(
                    "INSERT INTO accounts(run_id,meter,limit_units) VALUES (?,?,?)",
                    (run_id, meter, limit),
                )
            self._event(db, run_id, "RunCreated", {"request_id": request_id})
        return run_id, True

    def create_action_attempt(
        self,
        *,
        action: dict[str, Any],
        attempt: dict[str, Any],
        reservations: dict[str, int],
        decision_id: str | None = None,
        _db: sqlite3.Connection | None = None,
    ) -> None:
        """TX-Intent 一起写 Action、Attempt、预留和事件；可加入本连接初始 Run 准入，任一额度不足整项回滚。"""

        run_id = str(action["run_id"])
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.admission_transaction(_db) as db:
            run = db.execute(
                "SELECT state FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None or run["state"] != RunState.RUNNING.value:
                raise InvalidTransition("Run is not accepting new intents")

            db.execute(
                "INSERT INTO actions(action_id,run_id,kind,request_digest,target_name,before_digest,"
                "after_digest,old_text,new_text,expected_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    action["action_id"],
                    run_id,
                    action["kind"],
                    action["request_digest"],
                    action["target_name"],
                    action["before_digest"],
                    action["after_digest"],
                    action["old_text"],
                    action["new_text"],
                    action["expected_count"],
                ),
            )
            db.execute(
                "INSERT INTO attempts(attempt_id,action_id,run_id,attempt_no,state,envelope_digest) "
                "VALUES (?,?,?,?,?,?)",
                (
                    attempt["attempt_id"],
                    action["action_id"],
                    run_id,
                    attempt["attempt_no"],
                    AttemptState.INTENT.value,
                    attempt["envelope_digest"],
                ),
            )
            if decision_id is not None:
                owner = db.execute(
                    "SELECT run_id FROM step_decisions WHERE decision_id=?",
                    (decision_id,),
                ).fetchone()
                if owner is None or owner[0] != run_id:
                    raise ValueError("tool decision does not belong to this run")
                db.execute(
                    "INSERT INTO agent_tool_bindings VALUES (?,?)",
                    (decision_id, action["action_id"]),
                )

            for meter, amount in sorted(reservations.items()):
                if type(amount) is not int or amount < 0:
                    raise ValueError("reservation must be a non-negative integer")
                changed = db.execute(
                    "UPDATE accounts SET reserved=reserved+? "
                    "WHERE run_id=? AND meter=? "
                    "AND limit_units-settled-reserved-unknown_held>=?",
                    (amount, run_id, meter, amount),
                )
                if changed.rowcount != 1:
                    raise BudgetExceeded(
                        f"insufficient or missing budget meter: {meter}"
                    )
                db.execute(
                    "INSERT INTO reservations(attempt_id,run_id,meter,reserved_amount) VALUES (?,?,?,?)",
                    (attempt["attempt_id"], run_id, meter, amount),
                )
            self._event(
                db,
                run_id,
                "IntentRecorded",
                {"action_id": action["action_id"], "attempt_id": attempt["attempt_id"]},
            )

    def start_attempt(self, attempt_id: str, ticket_id: str) -> dict[str, Any]:
        """TX-Start 校验机会状态并固定唯一 Ticket；提交后派发才有开始资格，重复机会不得重新授权。"""

        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            row = db.execute(
                "SELECT a.*, r.state AS run_state FROM attempts a "
                "JOIN runs r ON r.run_id=a.run_id WHERE a.attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["run_state"] != RunState.RUNNING.value:
                raise InvalidTransition("Run is not allowed to start normal work")
            if row["state"] == AttemptState.TICKETED.value:
                existing = db.execute(
                    "SELECT * FROM tickets WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
                return dict(existing)
            if row["state"] != AttemptState.INTENT.value:
                raise InvalidTransition(f"Attempt cannot start from {row['state']}")

            db.execute(
                "INSERT INTO tickets(ticket_id,attempt_id,envelope_digest) VALUES (?,?,?)",
                (ticket_id, attempt_id, row["envelope_digest"]),
            )
            db.execute(
                "UPDATE attempts SET state=? WHERE attempt_id=?",
                (AttemptState.TICKETED.value, attempt_id),
            )
            self._event(
                db,
                row["run_id"],
                "TicketGranted",
                {"attempt_id": attempt_id, "ticket_id": ticket_id},
            )
            ticket = db.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            return dict(ticket)

    # 在当前事务调整 reserved/settled/unknown_held；未知用量保持占用而非按零释放。
    def _settle_reservations(
        self,
        db: sqlite3.Connection,
        *,
        attempt_id: str,
        usage: dict[str, int] | None,
        usage_known: bool,
    ) -> None:
        rows = db.execute(
            "SELECT * FROM reservations WHERE attempt_id=? ORDER BY meter",
            (attempt_id,),
        ).fetchall()
        for row in rows:
            meter = str(row["meter"])
            reserved = int(row["reserved_amount"])
            unknown_amount = int(row["unknown_amount"])
            if row["closed"]:
                if usage_known and unknown_amount > 0:
                    actual = int((usage or {}).get(meter, 0))
                    if actual < 0:
                        raise ValueError("usage cannot be negative")
                    db.execute(
                        "UPDATE accounts SET unknown_held=unknown_held-?, settled=settled+? "
                        "WHERE run_id=? AND meter=?",
                        (unknown_amount, actual, row["run_id"], meter),
                    )
                    db.execute(
                        "UPDATE reservations SET settled_amount=?, unknown_amount=0 "
                        "WHERE attempt_id=? AND meter=?",
                        (actual, attempt_id, meter),
                    )
                continue

            if usage_known:
                actual = int((usage or {}).get(meter, 0))
                if actual < 0:
                    raise ValueError("usage cannot be negative")
                db.execute(
                    "UPDATE accounts SET reserved=reserved-?, settled=settled+? "
                    "WHERE run_id=? AND meter=?",
                    (reserved, actual, row["run_id"], meter),
                )
                db.execute(
                    "UPDATE reservations SET settled_amount=?, unknown_amount=0, closed=1 "
                    "WHERE attempt_id=? AND meter=?",
                    (actual, attempt_id, meter),
                )
            else:
                db.execute(
                    "UPDATE accounts SET reserved=reserved-?, unknown_held=unknown_held+? "
                    "WHERE run_id=? AND meter=?",
                    (reserved, reserved, row["run_id"], meter),
                )
                db.execute(
                    "UPDATE reservations SET unknown_amount=?, closed=1 "
                    "WHERE attempt_id=? AND meter=?",
                    (reserved, attempt_id, meter),
                )

    def settle_receipt(self, receipt: ReceiptData, *, usage_known: bool = True) -> None:
        """核验 Attempt/envelope 后原子记录效果收据与资源结算；幂等重用不得重复扣费。"""

        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            attempt = db.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (receipt.attempt_id,)
            ).fetchone()
            if attempt is None:
                raise KeyError(receipt.attempt_id)
            if attempt["envelope_digest"] != receipt.envelope_digest:
                raise IdentityConflict(
                    "receipt does not belong to the frozen Attempt envelope"
                )

            existing = db.execute(
                "SELECT * FROM receipts WHERE receipt_id=?", (receipt.receipt_id,)
            ).fetchone()
            if existing is not None:
                expected = (
                    receipt.attempt_id,
                    receipt.envelope_digest,
                    receipt.outcome.value,
                    receipt.evidence_ref,
                    canonical_json(receipt.usage),
                )
                actual = (
                    existing["attempt_id"],
                    existing["envelope_digest"],
                    existing["outcome"],
                    existing["evidence_ref"],
                    existing["usage_json"],
                )
                if actual != expected:
                    raise IdentityConflict(
                        "receipt_id reused for different execution fact"
                    )
                return

            if attempt["state"] == AttemptState.RESOLVED.value:
                raise IdentityConflict("Attempt already resolved by another receipt")

            db.execute(
                "INSERT INTO receipts(receipt_id,attempt_id,envelope_digest,outcome,evidence_ref,usage_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    receipt.attempt_id,
                    receipt.envelope_digest,
                    receipt.outcome.value,
                    receipt.evidence_ref,
                    canonical_json(receipt.usage),
                ),
            )
            db.execute(
                "UPDATE attempts SET state=?, outcome=?, last_error=NULL WHERE attempt_id=?",
                (
                    AttemptState.RESOLVED.value,
                    receipt.outcome.value,
                    receipt.attempt_id,
                ),
            )
            self._settle_reservations(
                db,
                attempt_id=receipt.attempt_id,
                usage=receipt.usage,
                usage_known=usage_known,
            )
            self._event(
                db,
                attempt["run_id"],
                "AttemptSettled",
                {
                    "attempt_id": receipt.attempt_id,
                    "outcome": receipt.outcome.value,
                    "usage_known": usage_known,
                },
            )

    # 依据明确用量关闭 unknown_held；不修改已记录效果 outcome，也不凭推测清占用。
    def resolve_unknown_usage(self, attempt_id: str, usage: dict[str, int]) -> None:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            row = db.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            self._settle_reservations(
                db, attempt_id=attempt_id, usage=usage, usage_known=True
            )
            self._event(
                db,
                row["run_id"],
                "UsageResolved",
                {"attempt_id": attempt_id, "usage": usage},
            )

    # 把已派发不明机会及其资源预留转入 UNKNOWN；保留核对所需身份。
    def mark_attempt_unknown(self, attempt_id: str, reason: str) -> None:
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            row = db.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["state"] == AttemptState.RESOLVED.value:
                return
            db.execute(
                "UPDATE attempts SET state=?, outcome=?, last_error=? WHERE attempt_id=?",
                (AttemptState.UNKNOWN.value, Outcome.UNKNOWN.value, reason, attempt_id),
            )
            self._settle_reservations(
                db, attempt_id=attempt_id, usage=None, usage_known=False
            )
            self._event(
                db,
                row["run_id"],
                "AttemptUnknown",
                {"attempt_id": attempt_id, "reason": reason},
            )

    # 将候选摘要、验收版本、结论和证据绑定保存；模型 claim 不进入可信结论。
    def create_verification_report(
        self,
        *,
        run_id: str,
        action_id: str,
        candidate_digest: str,
        acceptance_version: str,
        verdict: Verdict,
        evidence_ref: str,
    ) -> str:
        report_id = f"vr_{uuid.uuid4().hex}"
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            if acceptance_version != run["acceptance_version"]:
                raise IdentityConflict(
                    "verification report uses the wrong acceptance version"
                )
            db.execute(
                "INSERT INTO verification_reports(report_id,run_id,action_id,candidate_digest,"
                "acceptance_version,verdict,evidence_ref) VALUES (?,?,?,?,?,?,?)",
                (
                    report_id,
                    run_id,
                    action_id,
                    candidate_digest,
                    acceptance_version,
                    verdict.value,
                    evidence_ref,
                ),
            )
            db.execute(
                "UPDATE runs SET state=? WHERE run_id=?",
                (RunState.VERIFYING.value, run_id),
            )
            self._event(
                db,
                run_id,
                "VerificationRecorded",
                {"report_id": report_id, "verdict": verdict.value},
            )
        return report_id

    # 在事务内验证匹配 PASS 报告后写唯一交付与 Run 终态；旧候选不能借新报告交付。
    def deliver(
        self, *, run_id: str, action_id: str, candidate_digest: str, report_id: str
    ) -> str:
        delivery_id = f"del_{uuid.uuid4().hex}"
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.tx() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            report = db.execute(
                "SELECT * FROM verification_reports WHERE report_id=?", (report_id,)
            ).fetchone()
            if run is None or report is None:
                raise KeyError("run or verification report not found")
            if report["run_id"] != run_id or report["action_id"] != action_id:
                raise IdentityConflict(
                    "verification report belongs to a different Run/Action"
                )
            if report["candidate_digest"] != candidate_digest:
                raise IdentityConflict(
                    "verification report belongs to a different candidate"
                )
            if report["verdict"] != Verdict.PASS.value:
                raise InvalidTransition("only a PASS report can authorize Delivery")
            if run["state"] in {RunState.CANCELLED.value, RunState.FAILED.value}:
                raise InvalidTransition("terminal control state forbids Delivery")

            existing = db.execute(
                "SELECT delivery_id FROM deliveries WHERE run_id=?", (run_id,)
            ).fetchone()
            if existing is not None:
                return str(existing["delivery_id"])
            db.execute(
                "INSERT INTO deliveries(delivery_id,run_id,action_id,candidate_digest,report_id) "
                "VALUES (?,?,?,?,?)",
                (delivery_id, run_id, action_id, candidate_digest, report_id),
            )
            db.execute(
                "UPDATE runs SET state=? WHERE run_id=?",
                (RunState.SUCCEEDED.value, run_id),
            )
            self._event(
                db,
                run_id,
                "Delivered",
                {"delivery_id": delivery_id, "report_id": report_id},
            )
        return delivery_id

    # 校验并读取 Core Run；返回状态数据，不暴露 SQL。
    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    # 读取 Run 最新 Action，供当前执行/恢复核对；无 Action 不捏造工作机会。
    def get_action_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM actions WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no action for {run_id}")
        return dict(row)

    # 校验稳定 Action 身份并读取固定意图。
    def get_action(self, action_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM actions WHERE action_id=?", (action_id,)
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return dict(row)

    # 读取指定 Action 最新 Attempt；重试必须尊重旧机会的结果状态。
    def get_attempt_for_action(self, action_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM attempts WHERE action_id=? ORDER BY attempt_no DESC LIMIT 1",
            (action_id,),
        ).fetchone()
        if row is None:
            raise KeyError(action_id)
        return dict(row)

    # 读取 Run 最新机会的投影；仅用于当前精确任务链。
    def get_attempt_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM attempts WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"no attempt for {run_id}")
        return dict(row)

    # 读取已签发凭证；Ticket 只证明开始资格，不证明效果成功。
    def get_ticket_for_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        return self._row(
            self.db.execute(
                "SELECT * FROM tickets WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
        )

    # 列出仍需核对的已派发机会；恢复循环不能另开效果绕过它。
    def get_pending_attempts(self, run_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT a.*, t.ticket_id FROM attempts a JOIN tickets t ON t.attempt_id=a.attempt_id "
            "WHERE a.state IN (?,?)"
        )
        args: list[Any] = [AttemptState.TICKETED.value, AttemptState.UNKNOWN.value]
        if run_id is not None:
            sql += " AND a.run_id=?"
            args.append(run_id)
        return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # 读取各资源 limit/settled/reserved/unknown_held；单位由 meter 名及合同定义。
    def get_accounts(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM accounts WHERE run_id=? ORDER BY meter", (run_id,)
            ).fetchall()
        ]

    # 按 Run sequence 读取持久事件；用于因果观测，不改变状态。
    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    # 取得唯一已验收交付记录；缺失即未获交付资格。
    def get_delivery(self, run_id: str) -> dict[str, Any] | None:
        return self._row(
            self.db.execute(
                "SELECT * FROM deliveries WHERE run_id=?", (run_id,)
            ).fetchone()
        )
