"""执行适配器：固定基线、受管读取、决策去重、对账与 OS 单写入者锁。

用户文件仅在提交时读取；以后只读写受管副本。锁在进程退出时释放，
不构成分布式 lease。对象发布在事务外，内部读投影与计量原子提交。
"""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
from ..acceptance import freeze_acceptance
from ..domain import RecoveryRequired, sha256_bytes


class LocalAgentExecution:
    def __init__(self, runtime, repository):
        self.runtime, self.repository = runtime, repository

    @contextmanager
    def lock(self, run_id):
        if not run_id.startswith("run_") or not run_id[4:].isalnum():
            raise ValueError("invalid run id")
        directory = self.runtime.runtime_dir / "driver-locks"
        directory.mkdir(exist_ok=True)
        with (directory / f"{run_id}.lock").open("a+b") as handle:
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise RecoveryRequired("another local driver owns this run") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise RecoveryRequired("another local driver owns this run") from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def freeze(self, run_id, allowed_files, acceptance):
        files = tuple(Path(p).resolve() for p in allowed_files)
        if not files or len(files) > 16 or len({p.name.casefold() for p in files}) != len(files):
            raise ValueError("allow 1-16 files with unique filenames; duplicate basenames are unsupported")
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

    def _files(self, run_id):
        return tuple(Path(p) for p in json.loads(self.repository.row(run_id)["allowed_files_json"]))

    def request_decision(self, run_id, step, provider, context):
        row = self.repository.row(run_id)
        return self.repository.decisions.request_decision(
            run_id=run_id, provider=provider, model=row["model_id"], allowed_files=self._files(run_id),
            context=context, max_output_tokens=row["max_output_tokens"], thinking=row["thinking"],
            request_key=f"{run_id}:step:{step}")

    def execute(self, run_id, decision_id, decision):
        args = decision.arguments or {}
        source = self.resolve(self._files(run_id), args.get("path"))
        managed = self.runtime.workspaces.path_for(run_id, source.name)
        if not managed.is_file():
            raise RecoveryRequired("fixed baseline is missing; never reread the user source")
        if decision.capability_id == "file.read":
            saved = self.runtime.store.db.execute("SELECT payload_json FROM agent_reads WHERE decision_id=? AND run_id=?", (decision_id, run_id)).fetchone()
            if saved:
                return json.loads(saved[0])
            offset, limit = args.get("offset", 0), args.get("limit", 3000)
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 3000:
                raise ValueError("offset >= 0 and 1 <= limit <= 3000, in Unicode characters")
            data = managed.read_bytes()
            text = data.decode("utf-8")
            preview = text[offset:offset + limit]
            snapshot = self.runtime.objects.put(data)
            payload = {"capability_id": "file.read", "source_file": str(source), "preview": preview,
                       "offset": offset, "next_offset": offset + len(preview), "total_chars": len(text),
                       "has_more": offset + len(preview) < len(text), "read_bytes": len(preview.encode("utf-8")),
                       "snapshot_ref": f"sha256:{snapshot}", "after_digest": snapshot}
            return self.repository.read_receipt(run_id, decision_id, payload)
        if decision.capability_id != "file.patch_exact":
            raise PermissionError("capability is not admitted")
        prepared = self.runtime.prepare_patch_action(run_id, source, old_text=args.get("old_text"),
                                                    new_text=args.get("new_text"), expected_count=args.get("expected_count"),
                                                    decision_id=decision_id)
        result = self.runtime.execute_patch_action(run_id, action_id=prepared["action_id"])
        receipt = result.get("receipt") or {}
        return {"capability_id": "file.patch_exact", "action_id": prepared["action_id"],
                "attempt_id": prepared["attempt_id"], "source_file": str(source), "managed_file": str(managed),
                "after_digest": prepared["after_digest"], "evidence_ref": receipt.get("evidence_ref", ""),
                "preview": managed.read_bytes().decode("utf-8")[:3000]}

    def recover(self, run_id):
        self.repository.decisions.recover(run_id)
        self.runtime.recover(run_id, deliver=False)
        models = self.repository.decisions.status(run_id)["model_invocations"]
        return not self.runtime.store.get_pending_attempts(run_id) and not any(m["state"] in {"TICKETED", "UNKNOWN"} for m in models)

    def current(self, run_id):
        result = {}
        for path in self._files(run_id):
            managed = self.runtime.workspaces.path_for(run_id, path.name)
            result[str(path)] = sha256_bytes(managed.read_bytes()) if managed.is_file() else "missing"
        return result

    def evidence(self, run_id):
        names = {p.name: str(p) for p in self._files(run_id)}
        return {a["evidence_ref"]: {**a, "source_file": names.get(a["target_name"])}
                for a in self.repository.status(run_id)["tool_actions"] if a.get("evidence_ref")}
