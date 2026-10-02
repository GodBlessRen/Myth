"""SQLite adapter for long-lived Goals, Triggers and explicit Personal State."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..core import GoalState
from ..domain import canonical_json
from ..domains.personal import TriggerKind


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS goals(
    goal_id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_runs(
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    relation TEXT NOT NULL DEFAULT 'work',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(goal_id, run_id)
);

CREATE TABLE IF NOT EXISTS goal_triggers(
    trigger_id TEXT PRIMARY KEY NOT NULL,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    kind TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personal_state(
    state_key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SqlitePersonalState:
    """Persistence only.  It does not schedule autonomous work by itself."""

    def __init__(self, runtime) -> None:
        self.store = runtime.store
        self.store.db.executescript(SCHEMA)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def create_goal(self, title: str, description: str = "") -> dict[str, Any]:
        name = str(title or "").strip()
        detail = str(description or "").strip()
        if not name or len(name) > 200:
            raise ValueError("goal title must contain 1-200 characters")
        if len(detail.encode("utf-8")) > 16_000:
            raise ValueError("goal description exceeds 16000 UTF-8 bytes")
        goal_id = self._id("goal")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO goals(goal_id,title,description,state) VALUES (?,?,?,?)",
                (goal_id, name, detail, GoalState.ACTIVE.value),
            )
        return self.goal(goal_id)

    def goal(self, goal_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM goals WHERE goal_id=?", (goal_id,)
        ).fetchone()
        if not row:
            raise KeyError(goal_id)
        return dict(row)

    def goals(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM goals"
        args: tuple[Any, ...] = ()
        if not include_archived:
            sql += " WHERE state<>?"
            args = (GoalState.ARCHIVED.value,)
        sql += " ORDER BY updated_at DESC,rowid DESC"
        return [dict(row) for row in self.store.db.execute(sql, args).fetchall()]

    def set_goal_state(self, goal_id: str, state: str | GoalState) -> dict[str, Any]:
        target = state if isinstance(state, GoalState) else GoalState(str(state))
        with self.store.tx() as db:
            updated = db.execute(
                "UPDATE goals SET state=?,updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
                (target.value, goal_id),
            ).rowcount
            if not updated:
                raise KeyError(goal_id)
        return self.goal(goal_id)

    def bind_run(self, goal_id: str, run_id: str, relation: str = "work") -> dict[str, Any]:
        self.goal(goal_id)
        run = self.store.get_run(run_id)
        value = str(relation or "work").strip()
        if not value or len(value) > 80:
            raise ValueError("goal/run relation must contain 1-80 characters")
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO goal_runs(goal_id,run_id,relation) VALUES (?,?,?)",
                (goal_id, run_id, value),
            )
        return {"goal_id": goal_id, "run_id": run["run_id"], "relation": value}

    def runs(self, goal_id: str) -> list[dict[str, Any]]:
        self.goal(goal_id)
        return [
            dict(row)
            for row in self.store.db.execute(
                "SELECT r.*,gr.relation,gr.created_at AS linked_at "
                "FROM goal_runs gr JOIN runs r ON r.run_id=gr.run_id "
                "WHERE gr.goal_id=? ORDER BY gr.created_at,r.rowid",
                (goal_id,),
            ).fetchall()
        ]

    def add_trigger(
        self,
        goal_id: str,
        kind: str | TriggerKind,
        spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.goal(goal_id)
        trigger_kind = kind if isinstance(kind, TriggerKind) else TriggerKind(str(kind))
        value = dict(spec or {})
        raw = canonical_json(value)
        if len(raw.encode("utf-8")) > 8_000:
            raise ValueError("trigger spec exceeds 8000 UTF-8 bytes")
        trigger_id = self._id("trigger")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO goal_triggers(trigger_id,goal_id,kind,spec_json) VALUES (?,?,?,?)",
                (trigger_id, goal_id, trigger_kind.value, raw),
            )
        return self.trigger(trigger_id)

    def trigger(self, trigger_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM goal_triggers WHERE trigger_id=?", (trigger_id,)
        ).fetchone()
        if not row:
            raise KeyError(trigger_id)
        value = dict(row)
        value["spec"] = json.loads(value.pop("spec_json"))
        value["enabled"] = bool(value["enabled"])
        return value

    def triggers(self, goal_id: str) -> list[dict[str, Any]]:
        self.goal(goal_id)
        rows = self.store.db.execute(
            "SELECT trigger_id FROM goal_triggers WHERE goal_id=? ORDER BY rowid",
            (goal_id,),
        ).fetchall()
        return [self.trigger(row["trigger_id"]) for row in rows]

    def set_state(self, key: str, value: Any) -> None:
        state_key = str(key or "").strip()
        if not state_key or len(state_key) > 120:
            raise ValueError("personal state key must contain 1-120 characters")
        raw = canonical_json(value)
        if len(raw.encode("utf-8")) > 16_000:
            raise ValueError("personal state value exceeds 16000 UTF-8 bytes")
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO personal_state(state_key,value_json) VALUES (?,?) "
                "ON CONFLICT(state_key) DO UPDATE SET value_json=excluded.value_json,"
                "updated_at=CURRENT_TIMESTAMP",
                (state_key, raw),
            )

    def state(self) -> dict[str, Any]:
        return {
            row["state_key"]: json.loads(row["value_json"])
            for row in self.store.db.execute(
                "SELECT state_key,value_json FROM personal_state ORDER BY state_key"
            ).fetchall()
        }
