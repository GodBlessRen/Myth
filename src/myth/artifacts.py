"""不可变对象、受管文件和收据日志的文件系统适配器。
SQLite 保存身份与投影，字节保存于此；单文件发布在数据库事务外完成，收据先发布再结算以支持进程崩溃后的核对。"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .domain import Outcome, ReceiptData, sha256_bytes


# 在平台支持时同步目录项；目录 fsync 不可用时降级，不能宣称所有文件系统都具备相同断电保证。
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
    """同目录临时文件写入并 fsync 后用 replace 发布；只保证单文件可见性，不是多文件或数据库事务。"""

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


# 内容寻址的不可变字节库；读取和发布均核验 SHA-256，损坏必须显式失败。
class ObjectStore:
    # 建立按摘要寻址的对象根；写入/读取时都核对字节身份，目录不等于数据库事务。
    def __init__(self, root: Path) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # 按内容摘要拆分目录；这是内部对象定位，调用方必须使用可信摘要。
    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest[2:]

    # 按字节摘要幂等发布对象，复用前/发布后校验；同摘要损坏立即报错。
    def put(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        path = self._path(digest)
        if path.exists():
            if sha256_bytes(path.read_bytes()) != digest:
                raise IOError(f"object corruption at {path}")
            return digest
        try:
            atomic_write(path, data)
        except (FileExistsError, PermissionError):
            # Windows 可能因另一个发布者正在读取同摘要对象而拒绝 replace。
            # 仅当目标已有完全相同字节才复用确定事实；路径不存在或内容冲突仍是失败，不盲重试。
            if not path.is_file() or path.read_bytes() != data:
                raise
        if sha256_bytes(path.read_bytes()) != digest:
            raise IOError(f"object failed post-publish digest check: {digest}")
        return digest

    # 读取对象并重新核对摘要，避免把损坏字节当作验收或恢复证据。
    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        data = path.read_bytes()
        if sha256_bytes(data) != digest:
            raise IOError(f"object digest mismatch: {digest}")
        return data


class ManagedWorkspace:
    """每 Run 受管文件目录；只接受普通文件名，已有基线内容冲突时拒绝覆盖。"""

    # 保存受管副本根目录；每个 Run 只能在自己的目录工作，原用户文件不由此覆盖。
    def __init__(self, root: Path) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # 校验普通文件名并映射到本 Run 目录；禁止路径穿越和 Windows drive/流标记。
    def path_for(self, run_id: str, target_name: str) -> Path:
        clean = Path(target_name).name
        if clean != target_name or clean in {"", ".", ".."} or ":" in clean:
            raise ValueError("target_name must be one plain file name")
        return self.root / run_id / clean

    # 首次发布冻结基线；已有文件仅相同字节可复用，不覆盖不同内容。
    def materialize(self, run_id: str, target_name: str, data: bytes) -> Path:
        path = self.path_for(run_id, target_name)
        if path.exists():
            current = path.read_bytes()
            if current != data:
                raise FileExistsError(
                    "managed baseline already exists with different bytes"
                )
            return path
        atomic_write(path, data)
        return path


class ReceiptJournal:
    """每 Attempt 的不可变执行日志；先于数据库结算发布，重复不同内容视为冲突。"""

    # 建立固定机会收据根；发布先于数据库结算，重复冲突内容不能覆盖。
    def __init__(self, root: Path) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # 定位某 Attempt 的固定日志路径；同机会始终映射同文件。
    def path_for(self, attempt_id: str) -> Path:
        return self.root / f"{attempt_id}.json"

    # 在 DB 结算前发布固定收据；重复相同内容复用，冲突内容拒绝覆盖。
    def publish(self, receipt: ReceiptData) -> Path:
        path = self.path_for(receipt.attempt_id)
        payload: dict[str, Any] = asdict(receipt)
        payload["outcome"] = receipt.outcome.value
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise IOError("conflicting receipt journal for the same Attempt")
            return path
        atomic_write(path, encoded)
        return path

    # 读取并还原持久效果事实；不存在返回空值，空值不能证明调用未开始。
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
