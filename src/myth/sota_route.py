"""SOTA Route：从已验收成功 Run 中学习更省的可观察执行路径。
只比较同任务/同冻结环境键；不读取或保存模型隐藏推理，不把低成本当成质量证据。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .domain import canonical_json, digest_json


# SOTA_ROUTE_SCHEMA：保存已验收路径快照；历史 Run 不因未来新纪录而被改写执行事实。
SOTA_ROUTE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS sota_route_runs(
    run_id TEXT PRIMARY KEY NOT NULL REFERENCES workspace_turns(run_id),
    comparison_key TEXT NOT NULL,
    task_key TEXT NOT NULL,
    model_key TEXT NOT NULL,
    environment_key TEXT NOT NULL,
    environment_scope TEXT NOT NULL,
    subject_digest TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    path_json TEXT NOT NULL,
    reasoning_json TEXT NOT NULL DEFAULT '{}',
    eligible INTEGER NOT NULL DEFAULT 1 CHECK(eligible IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS sota_route_runs_group
ON sota_route_runs(comparison_key, eligible);
"""

# CORE_COSTS：同质量通过后才比较的基础成本；这些字段都来自持久预算/步骤事实。
CORE_COSTS = (
    "model_calls",
    "tool_calls",
    "steps",
    "total_tokens",
    "write_bytes",
)

# OPTIONAL_COSTS：双方都真实测到时才加入比较；缺测不会被当成零。
OPTIONAL_COSTS = (
    "work_ms",
    "code_churn_lines",
    "human_attention_seconds",
)

# PROJECT_SKIP：项目状态指纹跳过版本库/依赖/秘钥目录；只用于“环境是否相同”的比较身份。
PROJECT_SKIP = {
    ".git", ".runtime", ".trash", ".venv", "venv", "node_modules", "__pycache__",
    ".aws", ".ssh", ".codex", ".myth", ".config", "secrets",
}
# PROJECT_TEXT_SUFFIXES：与当前项目文本工具的主范围对齐；二进制资产不作为首版 SOTA Route 可比条件。
PROJECT_TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".json", ".csv", ".yaml", ".yml", ".html",
    ".css", ".js", ".ts", ".tsx", ".jsx", ".toml", ".ini", ".cfg",
    ".xml", ".sh", ".ps1", ".go", ".rs", ".java", ".c", ".h", ".cpp",
}


# 只做轻量文本稳定化；不重写用户任务语义，代码/空格差异仍保留。
def _task_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


# 安全读取非负整数；bool/文本/负数不是实测成本。
def _measured_int(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


# 统计文本行；空字符串不伪造一行代码。
def _line_count(value) -> int:
    text = value if isinstance(value, str) else ""
    return len(text.splitlines()) if text else 0


# SOTA Route 状态所有者；负责路径快照、同条件比较和下一 Run 的冻结提示。
class SotaRouteLedger:
    # 保存共享 Runtime 连接并幂等建表；不拥有模型/工具执行权。
    def __init__(self, runtime) -> None:
        # runtime：对象库和 SQLite 生命周期仍由外层 Workspace 管理。
        self.runtime = runtime
        # store：只读取既有执行事实并保存 SOTA Route 派生账本。
        self.store = runtime.store
        self.store.ensure_schema(SOTA_ROUTE_SCHEMA)

    # 从固定设置生成模型条件键；不同模型/思考/上下文预算不混为同一比赛。
    def _model_key(self, settings: dict[str, Any]) -> str:
        fixed = {
            key: settings.get(key)
            for key in (
                "provider",
                "model",
                "thinking",
                "temperature",
                "num_ctx",
                "max_output_tokens",
                "max_steps",
            )
        }
        return digest_json(fixed)

    # 冻结项目文本状态摘要；读取只做 SHA-256，不把源码/秘钥正文写入 SOTA Route 账本。
    def freeze_environment(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        project = snapshot.get("project") or {}
        root_value = project.get("root")
        if not root_value:
            return {"scope": "frozen-context-v1", "project_digest": None, "files": 0, "bytes": 0}
        root = Path(root_value).resolve()
        if not root.is_dir():
            return {"scope": "project-unavailable-v1", "project_digest": None, "files": 0, "bytes": 0}
        digest = hashlib.sha256()
        files = 0
        total_bytes = 0
        complete = True
        try:
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(root)
                lowered = [part.lower() for part in relative.parts]
                if any(
                    part in PROJECT_SKIP
                    or part.startswith(".env")
                    or part.endswith((".key", ".pem"))
                    for part in lowered
                ):
                    continue
                if path.suffix.lower() not in PROJECT_TEXT_SUFFIXES:
                    continue
                size = path.stat().st_size
                if size > 1_000_000:
                    continue
                files += 1
                total_bytes += size
                if files > 10_000 or total_bytes > 64_000_000:
                    complete = False
                    break
                raw = path.read_bytes()
                digest.update(relative.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(hashlib.sha256(raw).digest())
        except OSError:
            complete = False
        return {
            "scope": "project-state-v1" if complete else "project-state-partial-v1",
            "project_digest": digest.hexdigest() if complete else None,
            "files": files,
            "bytes": total_bytes,
        }

    # 从冻结 Snapshot 生成环境键；显式排除 SOTA Route 自己，避免提示递归改变比较身份。
    def _environment_key(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        project = snapshot.get("project") or {}
        history_end = int(snapshot.get("turn_message_start") or 0)
        history = list(snapshot.get("messages") or [])[:history_end]
        knowledge = [
            {
                "source_ref": item.get("source_ref"),
                "citation": item.get("citation"),
                "resolution": item.get("resolution"),
                "resolution_offset": item.get("resolution_offset"),
            }
            for item in snapshot.get("knowledge") or []
        ]
        memory = [
            {
                "memory_id": item.get("memory_id"),
                "revision": item.get("revision"),
                "source_ref": item.get("source_ref"),
                "scope_type": item.get("scope_type"),
                "scope_id": item.get("scope_id"),
                "text_digest": digest_json({"text": item.get("text") or ""}),
            }
            for item in snapshot.get("memory") or []
        ]
        goal = snapshot.get("goal") or {}
        work = goal.get("work") or {}
        frozen_environment = snapshot.get("sota_route_environment") or {}
        environment = {
            "project": {
                "id": project.get("id"),
                "root": project.get("root"),
                "instructions": project.get("instructions"),
                "project_digest": frozen_environment.get("project_digest"),
                "project_files": frozen_environment.get("files"),
                "project_bytes": frozen_environment.get("bytes"),
            },
            "history": history,
            "knowledge": knowledge,
            "attached_document_ids": snapshot.get("attached_document_ids") or [],
            "memory": memory,
            "goal": {
                "goal_id": goal.get("goal_id"),
                "title": goal.get("title"),
                "description": goal.get("description"),
                "work": {
                    "revision": work.get("revision"),
                    "current_state": work.get("current_state"),
                    "progress_note": work.get("progress_note"),
                    "next_action": work.get("next_action"),
                    "waiting_for": work.get("waiting_for"),
                },
            },
            "intent_pick": snapshot.get("intent_pick") or {},
            "information_resolution": snapshot.get("information_resolution") or {},
            "policy_bindings": snapshot.get("policy_bindings") or {},
        }
        scope = str(
            frozen_environment.get("scope")
            or ("project-unfrozen-v1" if project.get("root") else "frozen-context-v1")
        )
        return digest_json(environment), scope

    # 为候选任务生成比较身份；只有三个键都相同的 Run 才会进入同一 SOTA Route 组。
    def identity(
        self,
        task: str,
        settings: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, str]:
        task_key = digest_json({"task": _task_text(task)})
        model_key = self._model_key(settings)
        environment_key, environment_scope = self._environment_key(snapshot)
        comparison_key = digest_json(
            {
                "task_key": task_key,
                "model_key": model_key,
                "environment_key": environment_key,
            }
        )
        return {
            "comparison_key": comparison_key,
            "task_key": task_key,
            "model_key": model_key,
            "environment_key": environment_key,
            "environment_scope": environment_scope,
        }

    # 读取 Run 当前用户任务；历史会话同样从准入 Snapshot 的本轮边界确定。
    def _task_for_turn(self, turn: dict[str, Any]) -> str:
        messages = list((turn.get("snapshot") or {}).get("messages") or [])
        start = int((turn.get("snapshot") or {}).get("turn_message_start") or 0)
        for item in reversed(messages[start:]):
            if item.get("role") == "user":
                return str(item.get("content") or "")
        for item in reversed(messages):
            if item.get("role") == "user":
                return str(item.get("content") or "")
        return ""

    # 读取 workspace_turns 原始行并还原设置/Snapshot；不经过 UI 投影，也不修改 Run。
    def _turn(self, run_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM workspace_turns WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        value = dict(row)
        value["settings"] = json.loads(value.pop("settings_json"))
        value["snapshot"] = json.loads(value.pop("snapshot_json"))
        return value

    # 从持久 Account、Step、Receipt 和人工关注记录汇总成本；缺失耗时保持 None。
    def metrics(self, run_id: str) -> dict[str, Any]:
        turn = self._turn(run_id)
        accounts = {
            row["meter"]: int(row["settled"])
            for row in self.store.db.execute(
                "SELECT meter,settled FROM accounts WHERE run_id=?", (run_id,)
            ).fetchall()
        }
        invocations = self.store.db.execute(
            "SELECT usage_json FROM model_invocations WHERE run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        model_wall_values = []
        model_wall_complete = True
        for row in invocations:
            try:
                usage = json.loads(row["usage_json"] or "{}")
            except json.JSONDecodeError:
                usage = {}
            calls = _measured_int(usage.get("model_calls"))
            wall = _measured_int(usage.get("provider_wall_ms"))
            if calls and wall is None:
                model_wall_complete = False
            if wall is not None:
                model_wall_values.append(wall)

        operations = self.store.db.execute(
            "SELECT decision_id,capability,state,tool_wall_ms FROM workspace_operations "
            "WHERE run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        tool_wall_complete = True
        tool_wall_values = []
        resolved_decisions = set()
        for row in operations:
            if row["state"] == "RESOLVED":
                resolved_decisions.add(row["decision_id"])
                wall = _measured_int(row["tool_wall_ms"])
                if wall is None:
                    tool_wall_complete = False
                else:
                    tool_wall_values.append(wall)
            else:
                tool_wall_complete = False

        files = set()
        code_added = 0
        code_removed = 0
        tool_proposals = 0
        ask_user = 0
        decision_rows = self.store.db.execute(
            "SELECT decision_id,decision_json FROM workspace_steps "
            "WHERE run_id=? AND decision_json IS NOT NULL ORDER BY step",
            (run_id,),
        ).fetchall()
        for row in decision_rows:
            try:
                decision = json.loads(row["decision_json"])
            except json.JSONDecodeError:
                continue
            kind = decision.get("decision_type")
            if kind == "tool_call":
                tool_proposals += 1
                if row["decision_id"] not in resolved_decisions:
                    continue
                args = decision.get("arguments") or {}
                capability = decision.get("capability_id")
                target = args.get("path")
                if isinstance(target, str) and target:
                    files.add(target.replace("\\", "/"))
                if capability in {"project.patch_exact", "file.patch_exact"}:
                    code_added += _line_count(args.get("new_text"))
                    code_removed += _line_count(args.get("old_text"))
                elif capability == "artifact.write":
                    code_added += _line_count(args.get("content"))
            elif kind == "ask_user":
                ask_user += 1

        attention = self.store.db.execute(
            "SELECT coalesce(sum(seconds),0) AS seconds,count(*) AS entries "
            "FROM delivery_attention WHERE run_id=?",
            (run_id,),
        ).fetchone()
        human_attention = (
            int(attention["seconds"]) if int(attention["entries"]) > 0 else None
        )
        model_wall = (
            sum(model_wall_values) if model_wall_complete else None
        )
        tool_wall = (
            sum(tool_wall_values) if tool_wall_complete else None
        )
        work_ms = (
            model_wall + tool_wall
            if model_wall is not None and tool_wall is not None
            else None
        )
        input_tokens = int(accounts.get("input_tokens", 0))
        output_tokens = int(accounts.get("output_tokens", 0))
        reasoning = self.reasoning(run_id)
        return {
            "model_calls": int(accounts.get("model_calls", 0)),
            "tool_calls": int(accounts.get("tool_calls", 0)),
            "tool_proposals": tool_proposals,
            "steps": int(turn.get("current_step") or 0),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "reasoning_tokens": reasoning["reasoning_tokens"],
            "write_bytes": int(accounts.get("write_bytes", 0)),
            "model_wall_ms": model_wall,
            "tool_wall_ms": tool_wall,
            "work_ms": work_ms,
            "code_added_lines": code_added,
            "code_removed_lines": code_removed,
            "code_churn_lines": code_added + code_removed,
            "files_written": len(files),
            "ask_user_count": ask_user,
            "human_attention_seconds": human_attention,
        }

    # 把可观察决定压成工具/提问/完成序列；不保存或推断模型隐藏 Chain-of-Thought。
    def path(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT step,decision_id,decision_json FROM workspace_steps "
            "WHERE run_id=? ORDER BY step",
            (run_id,),
        ).fetchall()
        result = []
        for row in rows:
            if not row["decision_json"]:
                continue
            try:
                decision = json.loads(row["decision_json"])
            except json.JSONDecodeError:
                continue
            kind = decision.get("decision_type")
            if kind == "tool_call":
                args = decision.get("arguments") or {}
                # 路径账本只保存可观察动作和小型定位字段，不复制源码、Prompt 或工具大参数。
                safe_args = {
                    key: args.get(key)
                    for key in ("path", "document_id", "profile_id", "resolution")
                    if isinstance(args.get(key), (str, int, float, bool))
                }
                item = {
                    "step": int(row["step"]),
                    "kind": "tool",
                    "decision_id": row["decision_id"],
                    "capability": decision.get("capability_id"),
                    "arguments": safe_args,
                }
            elif kind == "ask_user":
                item = {
                    "step": int(row["step"]),
                    "kind": "ask",
                    "decision_id": row["decision_id"],
                }
            else:
                item = {
                    "step": int(row["step"]),
                    "kind": "reply",
                    "decision_id": row["decision_id"],
                }
            result.append(item)
        return result

    # 读取供应商公开 Reasoning Summary 与可测推理成本；原始隐藏 CoT 永远不从这里推断。
    def reasoning(self, run_id: str) -> dict[str, Any]:
        attempts = []
        total_reasoning_tokens = 0
        reasoning_tokens_measured = False
        for row in self.store.db.execute(
            "SELECT model_attempt_id,model_id,response_ref,usage_json FROM model_invocations "
            "WHERE run_id=? AND outcome='SUCCEEDED' ORDER BY rowid",
            (run_id,),
        ).fetchall():
            try:
                usage = json.loads(row["usage_json"] or "{}")
            except json.JSONDecodeError:
                usage = {}
            measured_tokens = _measured_int(usage.get("reasoning_tokens"))
            if measured_tokens is not None:
                total_reasoning_tokens += measured_tokens
                reasoning_tokens_measured = True
            summaries: list[str] = []
            response_ref = row["response_ref"]
            if isinstance(response_ref, str) and response_ref:
                try:
                    raw = json.loads(
                        self.runtime.objects.get(response_ref).decode("utf-8")
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    raw = {}
                values = raw.get("reasoning_summary") if isinstance(raw, dict) else None
                if isinstance(values, list):
                    summaries = [
                        value.strip()[:4000]
                        for value in values
                        if isinstance(value, str) and value.strip()
                    ][:4]
            attempts.append(
                {
                    "model_attempt_id": row["model_attempt_id"],
                    "model_id": row["model_id"],
                    "reasoning_tokens": measured_tokens,
                    "summary": summaries,
                }
            )
        return {
            "reasoning_tokens": (
                total_reasoning_tokens if reasoning_tokens_measured else None
            ),
            "summary_available": any(item["summary"] for item in attempts),
            "attempts": attempts,
        }

    # 比较两个同质量 Run 的成本：A 所有基础成本不高于 B 且至少一项更低时，A beats B。
    def _beats(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        keys = list(CORE_COSTS)
        for key in OPTIONAL_COSTS:
            if a.get(key) is not None and b.get(key) is not None:
                keys.append(key)
        if not all(
            isinstance(a.get(key), (int, float))
            and isinstance(b.get(key), (int, float))
            for key in keys
        ):
            return False
        return all(a[key] <= b[key] for key in keys) and any(
            a[key] < b[key] for key in keys
        )

    # 读取一个比较组的已验收 Run，并标出当前 Champion group；不强行把不同权衡压成单一总分。
    def group(self, comparison_key: str) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT * FROM sota_route_runs WHERE comparison_key=? AND eligible=1 "
            "ORDER BY rowid",
            (comparison_key,),
        ).fetchall()
        values = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["path"] = json.loads(item.pop("path_json"))
            item["reasoning"] = json.loads(item.pop("reasoning_json"))
            values.append(item)
        for item in values:
            beaten_by = [
                other["run_id"]
                for other in values
                if other["run_id"] != item["run_id"]
                and self._beats(other["metrics"], item["metrics"])
            ]
            beats = [
                other["run_id"]
                for other in values
                if other["run_id"] != item["run_id"]
                and self._beats(item["metrics"], other["metrics"])
            ]
            item["status"] = "CHAMPION" if not beaten_by else "LOSER"
            item["lost_to"] = beaten_by[:8]
            item["beats"] = beats[:8]
        return values

    # 选择给模型看的 Champion 路线；Action Path + Reasoning Summary 都只是经验先验，不扩大权限。
    def hint_for_snapshot(
        self,
        task: str,
        settings: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any] | None:
        identity = self.identity(task, settings, snapshot)
        group = self.group(identity["comparison_key"])
        champions = [item for item in group if item["status"] == "CHAMPION"]
        if not champions:
            return None
        routes = []
        summaries = []
        for item in champions:
            route = [
                (
                    entry.get("capability")
                    if entry["kind"] == "tool"
                    else "ask_user" if entry["kind"] == "ask" else "reply"
                )
                for entry in item["path"]
            ]
            if route and route not in routes:
                routes.append(route)
            for attempt in (item.get("reasoning") or {}).get("attempts", []):
                for summary in attempt.get("summary") or []:
                    text = str(summary).strip()[:1200]
                    if text and text not in summaries:
                        summaries.append(text)
                    if len(summaries) >= 2:
                        break
                if len(summaries) >= 2:
                    break
            if len(routes) >= 2 and len(summaries) >= 2:
                break
        minima = {}
        for key in CORE_COSTS + (
            "work_ms",
            "code_churn_lines",
            "reasoning_tokens",
        ):
            values = [
                item["metrics"].get(key)
                for item in champions
                if isinstance(item["metrics"].get(key), (int, float))
            ]
            minima[key] = min(values) if values else None
        return {
            "comparison_key": identity["comparison_key"],
            "environment_scope": identity["environment_scope"],
            "passed_runs": len(group),
            "champion_runs": len(champions),
            "champion_costs": minima,
            "action_paths": routes,
            "reasoning_summaries": summaries,
            "rule": (
                "Use observable Champion experience as an efficiency prior only. "
                "Reasoning Summary is provider-visible summary, not hidden chain-of-thought. "
                "Do not skip required evidence or verification; deviate when current evidence requires it."
            ),
        }

    # 保存一个 PASSED Run 的路径和成本快照；重复同步只更新同一 run_id，不产生第二条冠军记录。
    def observe(self, run_id: str, *, subject_digest: str | None = None) -> dict[str, Any]:
        acceptance = self.store.db.execute(
            "SELECT state,subject_digest FROM delivery_acceptance WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if acceptance is None or acceptance["state"] != "PASSED":
            raise ValueError("SOTA Route only admits PASSED delivery")
        if (
            subject_digest is not None
            and subject_digest != acceptance["subject_digest"]
        ):
            raise ValueError("SOTA Route subject digest does not match current acceptance")
        turn = self._turn(run_id)
        if turn.get("status") != "COMPLETED":
            raise ValueError("SOTA Route requires a completed delivery")
        task = self._task_for_turn(turn)
        identity = self.identity(task, turn["settings"], turn["snapshot"])
        metrics = self.metrics(run_id)
        path = self.path(run_id)
        reasoning = self.reasoning(run_id)
        eligible = int(
            identity["environment_scope"] in {"frozen-context-v1", "project-state-v1"}
        )
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO sota_route_runs("
                "run_id,comparison_key,task_key,model_key,environment_key,environment_scope,"
                "subject_digest,metrics_json,path_json,reasoning_json,eligible"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "comparison_key=excluded.comparison_key,task_key=excluded.task_key,"
                "model_key=excluded.model_key,environment_key=excluded.environment_key,"
                "environment_scope=excluded.environment_scope,"
                "subject_digest=excluded.subject_digest,metrics_json=excluded.metrics_json,"
                "path_json=excluded.path_json,reasoning_json=excluded.reasoning_json,"
                "eligible=excluded.eligible,updated_at=CURRENT_TIMESTAMP",
                (
                    run_id,
                    identity["comparison_key"],
                    identity["task_key"],
                    identity["model_key"],
                    identity["environment_key"],
                    identity["environment_scope"],
                    acceptance["subject_digest"],
                    canonical_json(metrics),
                    canonical_json(path),
                    canonical_json(reasoning),
                    eligible,
                ),
            )
        return self.view(run_id)

    # Acceptance 离开 PASSED 时取消比较资格；历史快照仍保留审计，不从数据库抹除。
    def sync_acceptance(
        self,
        run_id: str,
        state: str,
        *,
        subject_digest: str | None = None,
    ) -> dict[str, Any] | None:
        if str(state).upper() == "PASSED":
            return self.observe(run_id, subject_digest=subject_digest)
        with self.store.tx() as db:
            db.execute(
                "UPDATE sota_route_runs SET eligible=0,updated_at=CURRENT_TIMESTAMP "
                "WHERE run_id=?",
                (run_id,),
            )
        return self.view(run_id)



    # 读取当前 Run 与同组 Champion 对比；未验收 Run 处于 WORKING，只观察实时成本与 Drift。
    def view(self, run_id: str) -> dict[str, Any]:
        turn = self._turn(run_id)
        task = self._task_for_turn(turn)
        identity = self.identity(task, turn["settings"], turn["snapshot"])
        metrics = self.metrics(run_id)
        reasoning = self.reasoning(run_id)
        group = self.group(identity["comparison_key"])
        current = next((item for item in group if item["run_id"] == run_id), None)
        champions = [item for item in group if item["status"] == "CHAMPION"]
        historical_champions = [
            item for item in champions if item["run_id"] != run_id
        ]
        minima = {}
        source = historical_champions or champions
        for key in CORE_COSTS + (
            "work_ms",
            "code_churn_lines",
            "reasoning_tokens",
        ):
            values = [
                item["metrics"].get(key)
                for item in source
                if isinstance(item["metrics"].get(key), (int, float))
            ]
            minima[key] = min(values) if values else None

        drift_reasons = []
        if historical_champions:
            champion_tools = minima.get("tool_calls")
            champion_steps = minima.get("steps")
            champion_tokens = minima.get("total_tokens")
            if (
                champion_tools is not None
                and metrics["tool_calls"] > champion_tools + 2
            ):
                drift_reasons.append("tool_calls")
            if (
                champion_steps is not None
                and metrics["steps"] > champion_steps + 2
            ):
                drift_reasons.append("steps")
            if (
                champion_tokens is not None
                and champion_tokens > 0
                and metrics["total_tokens"] > champion_tokens * 1.5
            ):
                drift_reasons.append("tokens")

        return {
            **identity,
            "eligible": bool(current and current.get("eligible")),
            "status": (
                current["status"]
                if current
                else "NOT_COMPARABLE"
                if identity["environment_scope"] in {
                    "project-state-partial-v1",
                    "project-unavailable-v1",
                    "project-unfrozen-v1",
                }
                else "WORKING"
            ),
            "metrics": metrics,
            "reasoning": reasoning,
            "action_path": self.path(run_id),
            "peer_count": len(group),
            "champion_count": len(champions),
            "champion_costs": minima,
            "lost_to": current["lost_to"] if current else [],
            "beats": current["beats"] if current else [],
            "drift": bool(drift_reasons),
            "drift_reasons": drift_reasons,
            "frozen_hint": (turn.get("snapshot") or {}).get("sota_route_hint"),
        }

    # 返回最近 SOTA Route 账本供诊断；列表不触发比较组重写或策略发布。
    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT run_id FROM sota_route_runs ORDER BY rowid DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [self.view(row["run_id"]) for row in rows]
