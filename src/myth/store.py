"""SQLite state owner for the minimal durable runtime.

The store exposes transaction-level use cases rather than cursors. It is the
single writer of Run/Action/Attempt/Ticket/Receipt/budget projections. Remote
or file effects never occur inside a SQLite transaction.
"""

from __future__ import annotations

from contextlib import contextmanager
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
"""


class RuntimeStore:
    """Own short durable transactions; callers own orchestration and I/O."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = FULL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

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

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return None if row is None else dict(row)

    def _event(self, db: sqlite3.Connection, run_id: str, kind: str, payload: dict[str, Any]) -> None:
        row = db.execute("SELECT next_sequence FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        seq = int(row[0])
        db.execute("UPDATE runs SET next_sequence=next_sequence+1 WHERE run_id=?", (run_id,))
        db.execute(
            "INSERT INTO events(run_id,sequence,kind,payload_json) VALUES (?,?,?,?)",
            (run_id, seq, kind, canonical_json(payload)),
        )

    def create_run(
        self,
        *,
        run_id: str,
        request_id: str,
        entry_digest: str,
        goal: str,
        acceptance_version: str,
        budgets: dict[str, int],
    ) -> tuple[str, bool]:
        with self.tx() as db:
            existing = db.execute(
                "SELECT run_id, entry_digest FROM runs WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing is not None:
                if existing["entry_digest"] != entry_digest:
                    raise IdentityConflict("request_id reused with different request content")
                return str(existing["run_id"]), False

            db.execute(
                "INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) "
                "VALUES (?,?,?,?,?,?)",
                (run_id, request_id, entry_digest, goal, acceptance_version, RunState.RUNNING.value),
            )
            for meter, limit in sorted(budgets.items()):
                if not meter or type(limit) is not int or limit < 0:
                    raise ValueError("budget meters require non-empty names and non-negative integer limits")
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
    ) -> None:
        """TX-Intent: action, attempt, all reservations, and event commit together."""

        run_id = str(action["run_id"])
        with self.tx() as db:
            run = db.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["state"] != RunState.RUNNING.value:
                raise InvalidTransition("Run is not accepting new intents")

            db.execute(
                "INSERT INTO actions(action_id,run_id,kind,request_digest,target_name,before_digest,"
                "after_digest,old_text,new_text,expected_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    action["action_id"], run_id, action["kind"], action["request_digest"],
                    action["target_name"], action["before_digest"], action["after_digest"],
                    action["old_text"], action["new_text"], action["expected_count"],
                ),
            )
            db.execute(
                "INSERT INTO attempts(attempt_id,action_id,run_id,attempt_no,state,envelope_digest) "
                "VALUES (?,?,?,?,?,?)",
                (
                    attempt["attempt_id"], action["action_id"], run_id, attempt["attempt_no"],
                    AttemptState.INTENT.value, attempt["envelope_digest"],
                ),
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
                    raise BudgetExceeded(f"insufficient or missing budget meter: {meter}")
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
        """TX-Start: one Attempt can receive at most one durable start Ticket."""

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
                existing = db.execute("SELECT * FROM tickets WHERE attempt_id=?", (attempt_id,)).fetchone()
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
            self._event(db, row["run_id"], "TicketGranted", {"attempt_id": attempt_id, "ticket_id": ticket_id})
            ticket = db.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            return dict(ticket)

    def _settle_reservations(
        self,
        db: sqlite3.Connection,
        *,
        attempt_id: str,
        usage: dict[str, int] | None,
        usage_known: bool,
    ) -> None:
        rows = db.execute(
            "SELECT * FROM reservations WHERE attempt_id=? ORDER BY meter", (attempt_id,)
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
        """TX-Settle: persist effect projection and meter projection without re-execution."""

        with self.tx() as db:
            attempt = db.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (receipt.attempt_id,)
            ).fetchone()
            if attempt is None:
                raise KeyError(receipt.attempt_id)
            if attempt["envelope_digest"] != receipt.envelope_digest:
                raise IdentityConflict("receipt does not belong to the frozen Attempt envelope")

            existing = db.execute(
                "SELECT * FROM receipts WHERE receipt_id=?", (receipt.receipt_id,)
            ).fetchone()
            if existing is not None:
                expected = (
                    receipt.attempt_id, receipt.envelope_digest, receipt.outcome.value,
                    receipt.evidence_ref, canonical_json(receipt.usage),
                )
                actual = (
                    existing["attempt_id"], existing["envelope_digest"], existing["outcome"],
                    existing["evidence_ref"], existing["usage_json"],
                )
                if actual != expected:
                    raise IdentityConflict("receipt_id reused for different execution fact")
                return

            if attempt["state"] == AttemptState.RESOLVED.value:
                raise IdentityConflict("Attempt already resolved by another receipt")

            db.execute(
                "INSERT INTO receipts(receipt_id,attempt_id,envelope_digest,outcome,evidence_ref,usage_json) "
                "VALUES (?,?,?,?,?,?)",
                (
                    receipt.receipt_id, receipt.attempt_id, receipt.envelope_digest,
                    receipt.outcome.value, receipt.evidence_ref, canonical_json(receipt.usage),
                ),
            )
            db.execute(
                "UPDATE attempts SET state=?, outcome=?, last_error=NULL WHERE attempt_id=?",
                (AttemptState.RESOLVED.value, receipt.outcome.value, receipt.attempt_id),
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

    def resolve_unknown_usage(self, attempt_id: str, usage: dict[str, int]) -> None:
        with self.tx() as db:
            row = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
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

    def mark_attempt_unknown(self, attempt_id: str, reason: str) -> None:
        with self.tx() as db:
            row = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None:
                raise KeyError(attempt_id)
            if row["state"] == AttemptState.RESOLVED.value:
                return
            db.execute(
                "UPDATE attempts SET state=?, outcome=?, last_error=? WHERE attempt_id=?",
                (AttemptState.UNKNOWN.value, Outcome.UNKNOWN.value, reason, attempt_id),
            )
            self._settle_reservations(db, attempt_id=attempt_id, usage=None, usage_known=False)
            self._event(db, row["run_id"], "AttemptUnknown", {"attempt_id": attempt_id, "reason": reason})

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
        with self.tx() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            if acceptance_version != run["acceptance_version"]:
                raise IdentityConflict("verification report uses the wrong acceptance version")
            db.execute(
                "INSERT INTO verification_reports(report_id,run_id,action_id,candidate_digest,"
                "acceptance_version,verdict,evidence_ref) VALUES (?,?,?,?,?,?,?)",
                (report_id, run_id, action_id, candidate_digest, acceptance_version, verdict.value, evidence_ref),
            )
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (RunState.VERIFYING.value, run_id))
            self._event(db, run_id, "VerificationRecorded", {"report_id": report_id, "verdict": verdict.value})
        return report_id

    def deliver(self, *, run_id: str, action_id: str, candidate_digest: str, report_id: str) -> str:
        delivery_id = f"del_{uuid.uuid4().hex}"
        with self.tx() as db:
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            report = db.execute(
                "SELECT * FROM verification_reports WHERE report_id=?", (report_id,)
            ).fetchone()
            if run is None or report is None:
                raise KeyError("run or verification report not found")
            if report["run_id"] != run_id or report["action_id"] != action_id:
                raise IdentityConflict("verification report belongs to a different Run/Action")
            if report["candidate_digest"] != candidate_digest:
                raise IdentityConflict("verification report belongs to a different candidate")
            if report["verdict"] != Verdict.PASS.value:
                raise InvalidTransition("only a PASS report can authorize Delivery")
            if run["state"] in {RunState.CANCELLED.value, RunState.FAILED.value}:
                raise InvalidTransition("terminal control state forbids Delivery")

            existing = db.execute("SELECT delivery_id FROM deliveries WHERE run_id=?", (run_id,)).fetchone()
            if existing is not None:
                return str(existing["delivery_id"])
            db.execute(
                "INSERT INTO deliveries(delivery_id,run_id,action_id,candidate_digest,report_id) "
                "VALUES (?,?,?,?,?)",
                (delivery_id, run_id, action_id, candidate_digest, report_id),
            )
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (RunState.SUCCEEDED.value, run_id))
            self._event(db, run_id, "Delivered", {"delivery_id": delivery_id, "report_id": report_id})
        return delivery_id

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def get_action_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM actions WHERE run_id=? ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no action for {run_id}")
        return dict(row)

    def get_attempt_for_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM attempts WHERE run_id=? ORDER BY rowid DESC LIMIT 1", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no attempt for {run_id}")
        return dict(row)

    def get_ticket_for_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        return self._row(self.db.execute("SELECT * FROM tickets WHERE attempt_id=?", (attempt_id,)).fetchone())

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

    def get_accounts(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM accounts WHERE run_id=? ORDER BY meter", (run_id,)).fetchall()]

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def get_delivery(self, run_id: str) -> dict[str, Any] | None:
        return self._row(self.db.execute("SELECT * FROM deliveries WHERE run_id=?", (run_id,)).fetchone())
