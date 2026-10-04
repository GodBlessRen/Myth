"""Control 命令、revision 与投影的 SQLite 所有者。
同事务读取、校验、分配 revision 并记录命令；安全点投影到工作区状态，晚到收据照常结算，Compact 按请求版本消费。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .control import ControlCommand, ControlService, ControlSnapshot
from ..domain import canonical_json


# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
# revision 是每 Run 的控制版本；(run_id,revision) 唯一，命令和投影在同一写事务分配。
# paused/stopped/compact_requested 是 0/1；stopped 表示停止未来调度。
# thinking_json 保存明确未来推理选项；payload_json 记录用户命令数据，不包含凭据/隐式授权。
SCHEMA = r"""
CREATE TABLE IF NOT EXISTS workspace_control_projection(
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES workspace_turns(run_id),
    revision INTEGER NOT NULL DEFAULT 1,
    paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
    stopped INTEGER NOT NULL DEFAULT 0 CHECK(stopped IN (0,1)),
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
    # 连接纯控制状态机与对话仓储，建立命令/投影表；revision 同事务分配，Turn/Core/Goal 通过状态所有者加入同一事务。
    def __init__(self, runtime, repository) -> None:
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.repository = repository
        # machine：纯控制状态机；只计算修订，持久化和 Run 投影由仓储负责。
        self.machine = ControlService()
        self.store.ensure_schema(SCHEMA)

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id() -> str:
        return f"cmd_{uuid.uuid4().hex}"

    def _ensure(self, db, run_id: str, settings: dict[str, Any]) -> None:
        """在当前事务里首次登记控制快照；配置取自 Turn 所有者，之后只由命令改变。"""
        db.execute(
            "INSERT OR IGNORE INTO workspace_control_projection"
            "(run_id,model,thinking_json) VALUES (?,?,?)",
            (run_id, settings.get("model"), canonical_json(settings.get("thinking"))),
        )

    def ensure(self, run_id: str) -> None:
        """幂等建立控制快照；初始化只读取当前 Turn，不接受调用者携带的旧设置。"""
        with self.store.tx() as db:
            target = self.repository.control_target(db, run_id)
            self._ensure(db, run_id, target["settings"])

    @staticmethod
    def _snapshot_from_row(row) -> ControlSnapshot:
        """把数据库值投影成纯状态机输入；命令 revision 仅为此 Run 的命令排序。"""
        if row is None:
            raise KeyError("control projection missing")
        return ControlSnapshot(
            revision=int(row["revision"]), paused=bool(row["paused"]), stopped=bool(row["stopped"]),
            model=row["model"], thinking=json.loads(row["thinking_json"]),
            steering_note=row["steering_note"], compact_requested=bool(row["compact_requested"]),
        )

    def _current(self, db, run_id: str) -> ControlSnapshot:
        """只读取当前连接事务的快照；不能把事务外旧读值带进写入安全点。"""
        return self._snapshot_from_row(db.execute(
            "SELECT * FROM workspace_control_projection WHERE run_id=?", (run_id,)
        ).fetchone())

    def _view(self, db, run_id: str) -> dict[str, Any]:
        """快照与历史来自同一事务；命令返回自己的提交版本，不混入下一条并发命令。"""
        snap = self._current(db, run_id)
        history = []
        for row in db.execute(
            "SELECT * FROM workspace_control_commands WHERE run_id=? ORDER BY revision", (run_id,)
        ):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            history.append(item)
        return {
            "revision": snap.revision, "paused": snap.paused, "stopped": snap.stopped,
            "model": snap.model, "thinking": snap.thinking, "steering_note": snap.steering_note,
            "compact_requested": snap.compact_requested, "commands": history,
        }

    def view(self, run_id: str) -> dict[str, Any]:
        """读取完整控制投影；仅在首次使用时登记默认快照，不改变 Turn/Goal 状态。"""
        with self.store.tx() as db:
            target = self.repository.control_target(db, run_id)
            self._ensure(db, run_id, target["settings"])
            return self._view(db, run_id)

    def command(self, run_id: str, command: str | ControlCommand, payload: Any = None,
                *, expected_revision: int | None = None) -> dict[str, Any]:
        """命令、设置、Turn/Core、Goal 和事件共用一次提交。

        模型目录的网络检查在事务外；expected_revision 把检查所依据的配置版本带回，
        若期间发生其他控制命令则拒绝旧检查结果，不能提交未经验证的模型/档位组合。
        """
        kind = ControlCommand(command)
        with self.store.tx() as db:
            target = self.repository.control_target(db, run_id)
            if target["status"] in {"COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"}:
                raise ValueError("terminal turn does not accept control commands")
            self._ensure(db, run_id, target["settings"])
            current = self._current(db, run_id)
            if expected_revision is not None and current.revision != expected_revision:
                raise ValueError("control changed during validation; retry with current settings")
            updated = self.machine.apply(current, kind, payload)
            db.execute(
                "UPDATE workspace_control_projection SET revision=?,paused=?,stopped=?,model=?,"
                "thinking_json=?,steering_note=?,compact_requested=?,updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (updated.revision, int(updated.paused), int(updated.stopped), updated.model,
                 canonical_json(updated.thinking), updated.steering_note, int(updated.compact_requested), run_id),
            )
            db.execute(
                "INSERT INTO workspace_control_commands(command_id,run_id,revision,command,payload_json) "
                "VALUES (?,?,?,?,?)", (self._id(), run_id, updated.revision, kind.value, canonical_json(payload)),
            )
            self.store.project_control(db, run_id, advance_revision=True)
            self.store._event(db, run_id, "ControlCommandCommitted",
                              {"command": kind.value, "revision": updated.revision})
            # 状态写入回到所有者；仓储只加入本事务，任何后半段故障会撤销上面的命令。
            self.repository.apply_control(db, run_id, updated, command=kind)
            return self._view(db, run_id)

    def gate(self, run_id: str) -> str | None:
        """在同一个写事务内读取控制并投影安全点；迟到 Pause 不能覆盖新回答或 Resume。"""
        with self.store.tx() as db:
            target = self.repository.control_target(db, run_id)
            self._ensure(db, run_id, target["settings"])
            return self.repository.apply_control(db, run_id, self._current(db, run_id))

    # 只消费生成该决定时使用的 Compact revision；旧决定不能清除更新的压缩请求。
    def consume_compaction(
        self, run_id: str, *, decision_id: str
    ) -> None:
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
