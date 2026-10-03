"""Control 命令、revision 与投影的 SQLite 所有者。
同事务读取、校验、分配 revision 并记录命令；安全点投影到工作区状态，晚到收据照常结算，Compact 按请求版本消费。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .control import ControlCommand, ControlService, ControlSnapshot
from ..domain import canonical_json


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
# revision 是每 Run 的控制版本；(run_id,revision) 唯一，命令和投影在同一写事务分配。
# paused/aborted/compact_requested 是 0/1；aborted 保留旧列合同，当前产品表达为 stopped。
# thinking_json 保存明确未来推理选项；payload_json 记录用户命令数据，不包含凭据/隐式授权。
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


# 控制命令和投影的持久协调器；写事务中分配 revision，安全点尊重晚到收据。
class SqliteControlService:
    # 连接纯控制状态机与对话仓储，建立命令/投影表；revision 同事务分配，跨表投影仍是已知共享数据库耦合。
    def __init__(self, runtime, repository) -> None:
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = repository
        # machine：纯控制状态机；只计算修订，持久化和 Run 投影由仓储负责。
        self.machine = ControlService()
        self.store.db.executescript(SCHEMA)

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id() -> str:
        return f"cmd_{uuid.uuid4().hex}"

    # 幂等初始化该 Turn 的控制投影；设置来自已保存 Turn，不以当前全局设置覆盖。
    def ensure(self, run_id: str, settings: dict[str, Any] | None = None) -> None:
        if settings is None:
            settings = self.repository.turn(run_id)["settings"]
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO workspace_control_projection"
                "(run_id,model,thinking_json) VALUES (?,?,?)",
                (
                    run_id,
                    settings.get("model"),
                    canonical_json(settings.get("thinking")),
                ),
            )

    # 把控制行映射为不可变快照；旧 aborted 列只表示当前 stopped 语义。
    @staticmethod
    def _snapshot_from_row(row) -> ControlSnapshot:
        if row is None:
            raise KeyError("control projection missing")
        return ControlSnapshot(
            revision=int(row["revision"]),
            paused=bool(row["paused"]),
            stopped=bool(row["aborted"]),
            model=row["model"],
            thinking=json.loads(row["thinking_json"]),
            steering_note=row["steering_note"],
            compact_requested=bool(row["compact_requested"]),
        )

    # 确保并读取当前持久控制快照；返回投影供安全点判断。
    def _snapshot(self, run_id: str) -> ControlSnapshot:
        self.ensure(run_id)
        row = self.store.db.execute(
            "SELECT * FROM workspace_control_projection WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._snapshot_from_row(row)

    # 生成当前控制事实与命令历史的只读投影；不是新的业务执行决定。
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

    # 在 BEGIN IMMEDIATE 内读取/校验当前 revision，并原子提交命令和投影；之后在安全点收束状态。
    def command(
        self, run_id: str, command: str | ControlCommand, payload: Any = None
    ) -> dict[str, Any]:
        kind = (
            command
            if isinstance(command, ControlCommand)
            else ControlCommand(str(command))
        )

        # BEGIN IMMEDIATE 在不同连接间串行分配 revision；读取当前状态、校验、递增和命令持久化一起提交。
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = db.execute(
                "SELECT status,settings_json FROM workspace_turns WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if turn is None:
                raise KeyError(run_id)
            if turn["status"] in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "BUDGET_EXHAUSTED",
            }:
                raise ValueError("terminal turn does not accept control commands")

            settings = json.loads(turn["settings_json"])
            db.execute(
                "INSERT OR IGNORE INTO workspace_control_projection"
                "(run_id,model,thinking_json) VALUES (?,?,?)",
                (
                    run_id,
                    settings.get("model"),
                    canonical_json(settings.get("thinking")),
                ),
            )
            row = db.execute(
                "SELECT * FROM workspace_control_projection WHERE run_id=?", (run_id,)
            ).fetchone()
            current = self._snapshot_from_row(row)
            updated = self.machine.apply(current, kind, payload)

            if kind is ControlCommand.SWITCH_MODEL:
                model = str(updated.model or "").strip()
                if not model or len(model) > 200:
                    raise ValueError("model must contain 1-200 characters")
                settings["model"] = model
            elif kind is ControlCommand.SWITCH_THINKING:
                settings["thinking"] = updated.thinking

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
                (
                    self._id(),
                    run_id,
                    updated.revision,
                    "stop" if kind is ControlCommand.ABORT else kind.value,
                    canonical_json(payload),
                ),
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

        # Run 状态是持久命令的安全点投影；Pause/Stop 后仍允许晚到模型/工具收据结算。
        if kind is ControlCommand.PAUSE:
            self.gate(run_id)
        elif kind is ControlCommand.RESUME:
            # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
            with self.store.tx() as db:
                row = db.execute(
                    "SELECT status FROM workspace_turns WHERE run_id=?", (run_id,)
                ).fetchone()
                if row and row["status"] == "PAUSED":
                    db.execute(
                        "UPDATE workspace_turns SET status='RUNNING',error=NULL WHERE run_id=?",
                        (run_id,),
                    )
                    db.execute(
                        "UPDATE runs SET state='RUNNING' WHERE run_id=?", (run_id,)
                    )
                    self.store._event(
                        db, run_id, "RunResumed", {"revision": updated.revision}
                    )
        elif kind in {ControlCommand.STOP, ControlCommand.ABORT}:
            self.gate(run_id)

        return self.view(run_id)

    def gate(self, run_id: str) -> str | None:
        """在安全点应用明确控制意图；停止/暂停未来工作，已发出效果不会被物理撤销。"""

        snap = self._snapshot(run_id)
        turn = self.repository.turn(run_id)
        if snap.stopped:
            if turn["status"] not in {
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "BUDGET_EXHAUSTED",
            }:
                self.repository.block(
                    run_id,
                    "CANCELLED",
                    "用户已终止本轮。已获 Ticket 的调用仍会保留真实晚到结果。",
                )
            return "CANCELLED"
        if snap.paused:
            if turn["status"] in {"RUNNING", "INTERRUPTED", "UNKNOWN"}:
                # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
                with self.store.tx() as db:
                    db.execute(
                        "UPDATE workspace_turns SET status='PAUSED',error=NULL WHERE run_id=?",
                        (run_id,),
                    )
                    db.execute(
                        "UPDATE runs SET state='PAUSED' WHERE run_id=?", (run_id,)
                    )
                    self.store._event(
                        db,
                        run_id,
                        "RunPaused",
                        {"revision": snap.revision, "safe_point": True},
                    )
            return "PAUSED"
        return None

    # 只消费生成该决定时使用的 Compact revision；旧决定不能清除更新的压缩请求。
    def consume_compaction(
        self, run_id: str, *, decision_id: str | None = None
    ) -> None:
        if decision_id is not None:
            row = self.store.db.execute(
                "SELECT m.request_ref FROM step_decisions d JOIN model_invocations m "
                "ON m.model_attempt_id=d.model_attempt_id WHERE d.decision_id=? AND m.run_id=?",
                (decision_id, run_id),
            ).fetchone()
            if row is None:
                return
            request = json.loads(self.runtime.objects.get(row["request_ref"]))
            report = request.get("context_report") or {}
            if not report.get("compact_requested"):
                return
            revision = report.get("control_revision")
        else:
            # 保留明确手动确认的兼容路径；正常 Agent 总传 decision_id，旧决定不能消费较新的 Compact。
            revision = self._snapshot(run_id).revision
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            changed = db.execute(
                "UPDATE workspace_control_projection SET compact_requested=0,"
                "updated_at=CURRENT_TIMESTAMP WHERE run_id=? AND revision=? AND compact_requested=1",
                (run_id, revision),
            )
            if changed.rowcount:
                self.store._event(
                    db,
                    run_id,
                    "ContextCompactionConsumed",
                    {
                        "revision": revision,
                        "decision_id": decision_id,
                    },
                )


# 保留旧公开仓储名的薄别名，不复制实现或数据库状态。
# SqliteControlPlane：旧仓储兼容名；新代码使用 SqliteControlService。
SqliteControlPlane = SqliteControlService
