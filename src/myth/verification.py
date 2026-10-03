"""受限项目测试 profile。
只执行用户显式信任项目中的 Python unittest profile；不提供任意 shell，也不声称具备 OS 级网络沙箱。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any

from .domain import canonical_json


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS workspace_verification_profiles(
    profile_id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL REFERENCES workspace_projects(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    test_dir TEXT NOT NULL,
    pattern TEXT NOT NULL,
    top_level TEXT,
    pythonpath_json TEXT NOT NULL DEFAULT '[]',
    timeout_seconds INTEGER NOT NULL,
    max_output_bytes INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    trusted_project INTEGER NOT NULL DEFAULT 1 CHECK(trusted_project IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS workspace_verification_profiles_project
ON workspace_verification_profiles(project_id);
"""

SAFE_ENV_KEYS = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL",
}


# 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
def _inside(root: Path, value: str, *, must_exist: bool = False) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("verification path is required")
    path = Path(raw)
    if path.is_absolute() or path.drive or ".." in path.parts or "\x00" in raw:
        raise PermissionError("verification path must be relative to the admitted project")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise PermissionError("verification path escapes admitted project")
    if must_exist and not resolved.exists():
        raise ValueError(f"verification path does not exist: {raw}")
    return resolved


# 该类型集中拥有当前职责，避免把状态真相分散到多个适配器。
class SqliteVerificationProfiles:
    """测试 profile 状态所有者与本机固定 argv 执行器。"""

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def __init__(self, runtime, repository) -> None:
        # 持有当前协作对象；生命周期与所属 Runtime/仓储一致。
        self.runtime = runtime
        # 持有当前协作对象；生命周期与所属 Runtime/仓储一致。
        self.store = runtime.store
        # 持有当前协作对象；生命周期与所属 Runtime/仓储一致。
        self.repository = repository
        self.store.db.executescript(SCHEMA)

    # 下列辅助入口保持边界显式，调用不隐式扩大权限或真实性。
    @staticmethod
    def _id() -> str:
        return f"verify_{uuid.uuid4().hex}"

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def create(self, project_id: str, value: dict[str, Any]) -> dict[str, Any]:
        self.repository.project(project_id)
        if value.get("trusted_project") is not True:
            raise ValueError(
                "test profiles execute project code; trusted_project=true is required"
            )
        name = str(value.get("name") or "Python unittest").strip()
        if not name or len(name) > 120:
            raise ValueError("verification profile name must contain 1-120 characters")
        kind = str(value.get("kind") or "python_unittest")
        if kind != "python_unittest":
            raise ValueError("only python_unittest profiles are supported")
        test_dir = str(value.get("test_dir") or "tests").strip()
        pattern = str(value.get("pattern") or "test*.py").strip()
        top_level = str(value.get("top_level") or "").strip() or None
        pythonpath = value.get("pythonpath") or []
        if (
            not isinstance(pythonpath, list)
            or len(pythonpath) > 8
            or any(not isinstance(item, str) for item in pythonpath)
        ):
            raise ValueError("pythonpath must be an array of at most 8 relative paths")
        if (
            not pattern or len(pattern) > 100 or "/" in pattern
            or "\\" in pattern or "\x00" in pattern
        ):
            raise ValueError("unittest pattern must be a simple file pattern")
        timeout = value.get("timeout_seconds", 120)
        output = value.get("max_output_bytes", 200_000)
        if type(timeout) is not int or not 1 <= timeout <= 900:
            raise ValueError("timeout_seconds must be 1-900")
        if type(output) is not int or not 4_096 <= output <= 2_000_000:
            raise ValueError("max_output_bytes must be 4096-2000000")
        profile_id = self._id()
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_verification_profiles("
                "profile_id,project_id,name,kind,test_dir,pattern,top_level,pythonpath_json,"
                "timeout_seconds,max_output_bytes,trusted_project"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                (
                    profile_id, project_id, name, kind, test_dir, pattern, top_level,
                    canonical_json(pythonpath), timeout, output,
                ),
            )
        return self.profile(profile_id)

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def profile(self, profile_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM workspace_verification_profiles WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        if not row:
            raise KeyError(profile_id)
        value = dict(row)
        value["pythonpath"] = json.loads(value.pop("pythonpath_json"))
        value["trusted_project"] = bool(value["trusted_project"])
        return value

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            self.repository.project(project_id)
            rows = self.store.db.execute(
                "SELECT profile_id FROM workspace_verification_profiles "
                "WHERE project_id=? ORDER BY rowid", (project_id,),
            ).fetchall()
        else:
            rows = self.store.db.execute(
                "SELECT profile_id FROM workspace_verification_profiles ORDER BY rowid"
            ).fetchall()
        return [self.profile(row["profile_id"]) for row in rows]

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def _contract(
        self, turn: dict[str, Any], profile_id: str
    ) -> tuple[dict[str, Any], Path, list[str], dict[str, str]]:
        profile = self.profile(str(profile_id or ""))
        project = (turn.get("snapshot") or {}).get("project") or {}
        if not project.get("id") or project["id"] != profile["project_id"]:
            raise PermissionError("verification profile belongs to another project")
        if not project.get("root"):
            raise ValueError("verification requires an admitted local project root")
        root = Path(project["root"]).resolve()
        if not root.is_dir():
            raise ValueError("admitted project root no longer exists")
        test_dir = _inside(root, profile["test_dir"], must_exist=True)
        top_level = (
            _inside(root, profile["top_level"], must_exist=True)
            if profile.get("top_level") else None
        )
        pythonpath = [
            str(_inside(root, item, must_exist=True)) for item in profile["pythonpath"]
        ]
        command = [
            sys.executable, "-X", "utf8", "-m", "unittest", "discover",
            "-s", str(test_dir.relative_to(root)), "-p", profile["pattern"], "-v",
        ]
        if top_level is not None:
            command += ["-t", str(top_level.relative_to(root))]
        env = {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}
        env["PYTHONUTF8"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if pythonpath:
            env["PYTHONPATH"] = os.pathsep.join(pythonpath)
        return profile, root, command, env

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def intent(self, turn: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        profile, root, command, _ = self._contract(turn, args.get("profile_id"))
        return {
            "write_bytes": 0,
            "requires_receipt": True,
            "profile_id": profile["profile_id"],
            "profile_revision": profile["revision"],
            "project_id": profile["project_id"],
            "kind": profile["kind"],
            "cwd": str(root),
            "command": command,
            "timeout_seconds": profile["timeout_seconds"],
            "max_output_bytes": profile["max_output_bytes"],
            "security": {
                "trusted_project_only": True,
                "arbitrary_shell": False,
                "credential_environment": "allowlist",
                "network_isolation": "not_provided",
            },
        }

    # 下列辅助入口保持边界显式，调用不隐式扩大权限或真实性。
    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
                taskkill = system_root / "System32" / "taskkill.exe"
                if taskkill.is_file():
                    subprocess.run(
                        [str(taskkill), "/PID", str(proc.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=5, check=False,
                    )
                else:
                    proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # 该入口按持久合同处理输入与输出，失败保持显式而不伪造完成。
    def run(self, turn: dict[str, Any], profile_id: str) -> dict[str, Any]:
        profile, root, command, env = self._contract(turn, profile_id)
        start = time.monotonic()
        timed_out = False
        returncode = None
        spawn_error = None
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            kwargs: dict[str, Any] = {
                "cwd": str(root), "env": env, "stdin": subprocess.DEVNULL,
                "stdout": stdout_file, "stderr": stderr_file, "close_fds": True,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            else:
                kwargs["start_new_session"] = True
            proc = None
            try:
                proc = subprocess.Popen(command, **kwargs)
                try:
                    returncode = proc.wait(timeout=profile["timeout_seconds"])
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._kill_tree(proc)
                    try:
                        returncode = proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        returncode = None
            except OSError as exc:
                spawn_error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
            limit = int(profile["max_output_bytes"])
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_raw = stdout_file.read(limit + 1)
            stderr_raw = stderr_file.read(limit + 1)
        result = {
            "capability_id": "test.run",
            "status": (
                "PASSED"
                if returncode == 0 and not timed_out and not spawn_error
                else "FAILED"
            ),
            "profile_id": profile["profile_id"],
            "profile_revision": profile["revision"],
            "returncode": returncode,
            "timed_out": timed_out,
            "spawn_error": spawn_error,
            "elapsed_ms": elapsed_ms,
            "stdout": stdout_raw[:limit].decode("utf-8", errors="replace"),
            "stderr": stderr_raw[:limit].decode("utf-8", errors="replace"),
            "stdout_truncated": len(stdout_raw) > limit,
            "stderr_truncated": len(stderr_raw) > limit,
            "command": "python -m unittest discover",
            "security": {
                "trusted_project_only": True,
                "arbitrary_shell": False,
                "credential_environment": "allowlist",
                "network_isolation": "not_provided",
            },
        }
        digest = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
        result["evidence_ref"] = f"test:{profile['profile_id']}@{digest}"
        return result
