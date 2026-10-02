"""Content-addressed objects, managed workspaces, and crash-safe receipt journal.

The database stores identities and projections; immutable bytes live here.
Receipt journal files intentionally exist outside SQLite so a process can die
after the external effect and still leave evidence that recovery can settle.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .domain import Outcome, ReceiptData, sha256_bytes


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    """Publish one file atomically within a filesystem; not a multi-file transaction."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:]

    def put(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        path = self._path(digest)
        if path.exists():
            if sha256_bytes(path.read_bytes()) != digest:
                raise IOError(f"object corruption at {path}")
            return digest
        atomic_write(path, data)
        if sha256_bytes(path.read_bytes()) != digest:
            raise IOError(f"object failed post-publish digest check: {digest}")
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        data = path.read_bytes()
        if sha256_bytes(data) != digest:
            raise IOError(f"object digest mismatch: {digest}")
        return data


class ManagedWorkspace:
    """Single-writer managed files; v1 deliberately does not edit user files in place."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str, target_name: str) -> Path:
        clean = Path(target_name).name
        if clean != target_name or clean in {"", ".", ".."} or ":" in clean:
            raise ValueError("target_name must be one plain file name")
        return self.root / run_id / clean

    def materialize(self, run_id: str, target_name: str, data: bytes) -> Path:
        path = self.path_for(run_id, target_name)
        if path.exists():
            current = path.read_bytes()
            if current != data:
                raise FileExistsError("managed baseline already exists with different bytes")
            return path
        atomic_write(path, data)
        return path


class ReceiptJournal:
    """Durable per-Attempt execution evidence written before DB settlement."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, attempt_id: str) -> Path:
        return self.root / f"{attempt_id}.json"

    def publish(self, receipt: ReceiptData) -> Path:
        path = self.path_for(receipt.attempt_id)
        payload: dict[str, Any] = asdict(receipt)
        payload["outcome"] = receipt.outcome.value
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise IOError("conflicting receipt journal for the same Attempt")
            return path
        atomic_write(path, encoded)
        return path

    def read(self, attempt_id: str) -> ReceiptData | None:
        path = self.path_for(attempt_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ReceiptData(
            receipt_id=raw["receipt_id"],
            attempt_id=raw["attempt_id"],
            envelope_digest=raw["envelope_digest"],
            outcome=Outcome(raw["outcome"]),
            evidence_ref=raw["evidence_ref"],
            usage={str(k): int(v) for k, v in raw.get("usage", {}).items()},
        )
