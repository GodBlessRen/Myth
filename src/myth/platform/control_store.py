"""Persistent Control service for conversation Runs.

Commands are durable facts.  They may change future planning at safe points,
but they never rewrite an already-issued model/tool Ticket or erase a late
Receipt.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .control import ControlCommand, ControlService, ControlSnapshot
from ..domain import canonical_json


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS workspace_control_projection(
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES workspace_turns(run_id),
    revision INTEGER NOT NULL DEFAULT 1,
    paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
    aborted INTEGER NOT NULL DEFAULT 0 CHECK(aborted IN (0,1)),
    model TEXT,
    thinking_json TEXT NOT NULL DEFAULT 'null',
    steering_note TEXT,
    compact_requested INTEGER NOT NULL DEFAULT 0 CHECK(compact_requested IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_control_commands(
    command_id TEXT PRIMARY KEY NOT NULL,
    run_id TEXT NOT NULL REFERENCES workspace_turns(run_id),
    revision INTEGER NOT NULL,
    command TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, revision)
);
"""


class SqliteControlService:
    def __init__(self, runtime, repository) -> None:
        self.runtime = runtime
        self.store = runtime.store
        self.repository = repository
        self.machine = ControlService()
        self.store.db.executescript(SCHEMA)

    @staticmethod
    def _id() -> str:
        return f"cmd_{uuid.uuid4().hex}"

    def ensure(self, run_id: str, settings: dict[str, Any] | None = None) -> None:
        if settings is None:
            settings = self.repository.turn(run_id)["settings"]
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO workspace_control_projection"
                "(run_id,model,thinking_json) VALUES (?,?,?)",
                (run_id, settings.get("model"), canonical_json(settings.get("thinking"))),
            )

    def _snapshot(self, run_id: str) -> ControlSnapshot:
        self.ensure(run_id)
        row = self.store.db.execute(
            "SELECT * FROM workspace_control_projection WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return ControlSnapshot(
            revision=int(row["revision"]),
            paused=bool(row["paused"]),
            stopped=bool(row["aborted"]),
            model=row["model"],
            thinking=json.loads(row["thinking_json"]),
            steering_note=row["steering_note"],
            compact_requested=bool(row["compact_requested"]),
        )

    def view(self, run_id: str) -> dict[str, Any]:
        snap = self._snapshot(run_id)
        history = [
            {
                **dict(row),
                "payload": json.loads(row["payload_json"]),
            }
            for row in self.store.db.execute(
                "SELECT * FROM workspace_control_commands WHERE run_id=? ORDER BY revision",
                (run_id,),
            ).fetchall()
        ]
        for item in history:
            item.pop("payload_json", None)
        return {
            "revision": snap.revision,
            "paused": snap.paused,
            "stopped": snap.stopped,
            "aborted": snap.stopped,
            "model": snap.model,
            "thinking": snap.thinking,
            "steering_note": snap.steering_note,
            "compact_requested": snap.compact_requested,
            "commands": history,
        }

    def command(self, run_id: str, command: str | ControlCommand, payload: Any = None) -> dict[str, Any]:
        kind = command if isinstance(command, ControlCommand) else ControlCommand(str(command))
        turn = self.repository.turn(run_id)
        if turn["status"] in {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}:
            raise ValueError("terminal turn does not accept control commands")

        current = self._snapshot(run_id)
        updated = self.machine.apply(current, kind, payload)
        settings = dict(turn["settings"])

        if kind is ControlCommand.SWITCH_MODEL:
            model = str(updated.model or "").strip()
            if not model or len(model) > 200:
                raise ValueError("model must contain 1-200 characters")
            settings["model"] = model
        elif kind is ControlCommand.SWITCH_THINKING:
            settings["thinking"] = updated.thinking

        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_control_projection SET revision=?,paused=?,aborted=?,model=?,"
                "thinking_json=?,steering_note=?,compact_requested=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE run_id=?",
                (
                    updated.revision,
                    int(updated.paused),
                    int(updated.aborted),
                    updated.model,
                    canonical_json(updated.thinking),
                    updated.steering_note,
                    int(updated.compact_requested),
                    run_id,
                ),
            )
            db.execute(
                "INSERT INTO workspace_control_commands(command_id,run_id,revision,command,payload_json) "
                "VALUES (?,?,?,?,?)",
                (self._id(), run_id, updated.revision, "stop" if kind is ControlCommand.ABORT else kind.value, canonical_json(payload)),
            )
            if kind in {ControlCommand.SWITCH_MODEL, ControlCommand.SWITCH_THINKING}:
                db.execute(
                    "UPDATE workspace_turns SET settings_json=? WHERE run_id=?",
                    (canonical_json(settings), run_id),
                )
            db.execute(
                "UPDATE runs SET control_revision=? WHERE run_id=?",
                (updated.revision, run_id),
            )
            self.store._event(
                db,
                run_id,
                "ControlCommandCommitted",
                {"command": kind.value, "revision": updated.revision},
            )

        # Status changes are projections of the durable command.  Late model/tool
        # receipts are still allowed to settle after pause/stop.
        if kind is ControlCommand.PAUSE:
            self.gate(run_id)
        elif kind is ControlCommand.RESUME:
            with self.store.tx() as db:
                row = db.execute(
                    "SELECT status FROM workspace_turns WHERE run_id=?", (run_id,)
                ).fetchone()
                if row and row["status"] == "PAUSED":
                    db.execute(
                        "UPDATE workspace_turns SET status='RUNNING',error=NULL WHERE run_id=?",
                        (run_id,),
                    )
                    db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,))
                    self.store._event(db, run_id, "RunResumed", {"revision": updated.revision})
        elif kind in {ControlCommand.STOP, ControlCommand.ABORT}:
            self.gate(run_id)

        return self.view(run_id)

    def gate(self, run_id: str) -> str | None:
        """Project durable control intent at an Agent safe point."""

        snap = self._snapshot(run_id)
        turn = self.repository.turn(run_id)
        if snap.stopped:
            if turn["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}:
                self.repository.block(
                    run_id,
                    "CANCELLED",
                    "用户已终止本轮。已获 Ticket 的调用仍会保留真实晚到结果。",
                )
            return "CANCELLED"
        if snap.paused:
            if turn["status"] in {"RUNNING", "UNKNOWN"}:
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE workspace_turns SET status='PAUSED',error=NULL WHERE run_id=?",
                        (run_id,),
                    )
                    db.execute("UPDATE runs SET state='PAUSED' WHERE run_id=?", (run_id,))
                    self.store._event(
                        db,
                        run_id,
                        "RunPaused",
                        {"revision": snap.revision, "safe_point": True},
                    )
            return "PAUSED"
        return None

    def consume_compaction(self, run_id: str) -> None:
        if not self._snapshot(run_id).compact_requested:
            return
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_control_projection SET compact_requested=0,"
                "updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (run_id,),
            )
            self.store._event(db, run_id, "ContextCompactionConsumed", {})




# v0.8 compatibility alias.
SqliteControlPlane = SqliteControlService
