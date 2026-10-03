"""Exact Agent 与 Conversation 共用的本机 Driver 锁。
只依赖目录与 Run 身份，避免为取锁实例化另一个业务执行器；OS 退出释放物理锁，Lease 与收据分别承担负责人记录和效果事实。"""

from contextlib import contextmanager
import os
from pathlib import Path

from ..domain import RecoveryRequired


@contextmanager
def local_run_lock(runtime_dir: Path, run_id: str):
    """非阻塞取得单个 Run 的本机执行锁，finally 释放；仅互斥驱动，不授予工具权限或证明调用成功。"""
    if not run_id.startswith("run_") or not run_id[4:].isalnum():
        raise ValueError("invalid run id")
    directory = Path(runtime_dir) / "driver-locks"
    directory.mkdir(exist_ok=True)
    with (directory / f"{run_id}.lock").open("a+b") as handle:
        # Windows 锁定首字节；先保证字节存在，再把游标回到同一锁定位置。
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
            # 释放物理锁不改变任何 Run/Receipt；恢复仍读取持久事实。
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
