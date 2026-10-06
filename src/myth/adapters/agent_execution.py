"""Exact Agent 的本机执行适配器。
固定用户文件基线，读取和修改受管副本，复用模型/工具收据；本机单 Run 锁由独立共享适配器提供。"""

from __future__ import annotations
import json
from pathlib import Path
from .driver_lock import local_run_lock
from ..acceptance import freeze_acceptance
from ..domain import RecoveryRequired, sha256_bytes


# Exact 用例的文件/模型执行器；依赖允许文件白名单和固定受管副本，不能随意重读用户源文件。
class LocalAgentExecution:
    # 连接受管文件、模型决定和只读观察；只保存协作者，效果必须由各方法取得 Ticket 后发生。
    def __init__(self, runtime, repository):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.runtime, self.repository = runtime, repository

    # 取得一个 Run 的本机执行互斥作用域；竞争不表示效果失败，需按恢复事实判断后续。
    def lock(self, run_id):
        return local_run_lock(self.runtime.runtime_dir, run_id)

    # 校验 1–16 个唯一文件名并冻结 UTF-8 基线/验收；发布受管副本在 DB 外，源文件以后不作为可变基线。
    def freeze(self, run_id, allowed_files, acceptance):
        files = tuple(Path(p).resolve() for p in allowed_files)
        if (
            not files
            or len(files) > 16
            or len({p.name.casefold() for p in files}) != len(files)
        ):
            raise ValueError(
                "allow 1-16 files with unique filenames; duplicate basenames are unsupported"
            )
        baseline = {}
        for path in files:
            if not path.is_file() or path.stat().st_size > 1_000_000:
                raise ValueError("allowed files must exist and be at most 1 MB each")
            baseline[str(path)] = path.read_bytes()
            baseline[str(path)].decode("utf-8")
        rules = []
        for raw in acceptance:
            rule = dict(raw)
            rule["path"] = str(self.resolve(files, raw.get("path")))
            rules.append(rule)
        manifest = freeze_acceptance(baseline, rules)
        for path in files:
            data = baseline[str(path)]
            self.runtime.objects.put(data)
            self.runtime.workspaces.materialize(run_id, path.name, data)
        return files, manifest

    # 校验范围后解析目标；范围身份来自已准入输入，不能让模型参数扩大权限。
    def resolve(self, files, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path must be a non-empty string")
        raw = Path(value)
        if raw.is_absolute():
            candidate = raw.resolve()
        else:
            candidate = (self.runtime.root / raw).resolve()
            if candidate not in files and len(raw.parts) == 1:
                candidate = next((p for p in files if p.name == raw.name), candidate)
        if candidate not in files:
            raise PermissionError("path is outside this run's explicit allowed_files")
        return candidate

    # 还原 Run 创建时固定的绝对允许路径；模型参数不能新增路径。
    def _files(self, run_id):
        return tuple(
            Path(p)
            for p in json.loads(self.repository.row(run_id)["allowed_files_json"])
        )

    # 固定步骤请求身份，读取/生成持久决定；供应商结果不明时先恢复而非重新调用。
    def request_decision(self, run_id, step, provider, context):
        row = self.repository.row(run_id)
        return self.repository.decisions.request_decision(
            run_id=run_id,
            provider=provider,
            model=row["model_id"],
            allowed_files=self._files(run_id),
            context=context,
            max_output_tokens=row["max_output_tokens"],
            thinking=row["thinking"],
            request_key=f"{run_id}:step:{step}",
        )

    # 执行已校验/准入的工作并留下结果证据；已存在稳定绑定时复用事实而非重复效果。
    def execute(self, run_id, decision_id, decision):
        # 先锁定准入时的受管基线；读复用原收据，精确补丁走 Core Ticket/Receipt，不能改读用户原件。
        args = decision.arguments or {}
        source = self.resolve(self._files(run_id), args.get("path"))
        managed = self.runtime.workspaces.path_for(run_id, source.name)
        if not managed.is_file():
            raise RecoveryRequired(
                "fixed baseline is missing; never reread the user source"
            )
        if decision.capability_id == "file.read":
            saved = self.runtime.store.db.execute(
                "SELECT payload_json FROM agent_reads WHERE decision_id=? AND run_id=?",
                (decision_id, run_id),
            ).fetchone()
            if saved:
                return json.loads(saved[0])
            offset, limit = args.get("offset", 0), args.get("limit", 3000)
            if (
                type(offset) is not int
                or offset < 0
                or type(limit) is not int
                or not 1 <= limit <= 3000
            ):
                raise ValueError(
                    "offset >= 0 and 1 <= limit <= 3000, in Unicode characters"
                )
            data = managed.read_bytes()
            text = data.decode("utf-8")
            preview = text[offset : offset + limit]
            snapshot = self.runtime.objects.put(data)
            payload = {
                "capability_id": "file.read",
                "source_file": str(source),
                "preview": preview,
                "offset": offset,
                "next_offset": offset + len(preview),
                "total_chars": len(text),
                "has_more": offset + len(preview) < len(text),
                "read_bytes": len(preview.encode("utf-8")),
                "snapshot_ref": f"sha256:{snapshot}",
                "after_digest": snapshot,
            }
            return self.repository.read_receipt(run_id, decision_id, payload)
        if decision.capability_id != "file.patch_exact":
            raise PermissionError("capability is not admitted")
        prepared = self.runtime.prepare_patch_action(
            run_id,
            source,
            old_text=args.get("old_text"),
            new_text=args.get("new_text"),
            expected_count=args.get("expected_count"),
            decision_id=decision_id,
        )
        result = self.runtime.execute_patch_action(
            run_id, action_id=prepared["action_id"]
        )
        receipt = result.get("receipt") or {}
        return {
            "capability_id": "file.patch_exact",
            "action_id": prepared["action_id"],
            "attempt_id": prepared["attempt_id"],
            "source_file": str(source),
            "managed_file": str(managed),
            "after_digest": prepared["after_digest"],
            "evidence_ref": receipt.get("evidence_ref", ""),
            "preview": managed.read_bytes().decode("utf-8")[:3000],
        }

    # 用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。
    def recover(self, run_id):
        self.repository.decisions.recover(run_id)
        self.runtime.recover(run_id, deliver=False)
        models = self.repository.decisions.status(run_id)["model_invocations"]
        return not self.runtime.store.get_pending_attempts(run_id) and not any(
            m["state"] in {"TICKETED", "UNKNOWN"} for m in models
        )

    # 读取受管候选的当前摘要；不重新读取用户原文件改变冻结基线。
    def current(self, run_id):
        result = {}
        for path in self._files(run_id):
            managed = self.runtime.workspaces.path_for(run_id, path.name)
            result[str(path)] = (
                sha256_bytes(managed.read_bytes()) if managed.is_file() else "missing"
            )
        return result

    # 投影该 Run 的真实工具收据与来源；只提供已记录证据，不替模型声明补造效果。
    def evidence(self, run_id):
        names = {p.name: str(p) for p in self._files(run_id)}
        return {
            a["evidence_ref"]: {**a, "source_file": names.get(a["target_name"])}
            for a in self.repository.status(run_id)["tool_actions"]
            if a.get("evidence_ref")
        }
