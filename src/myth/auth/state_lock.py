"""认证聚合共享的本机文件锁；只串行凭据轮转，不参与 Runtime 授权。"""

import os
from pathlib import Path
import time


class AuthStateLock:
    """每次上下文拥有一个句柄；超时与清理失败不伪造认证成功。"""

    def __init__(self, path: Path, timeout: float, busy_error: Exception):
        """只保存锁地址和等待合同；进入上下文时才创建句柄、争抢 OS 锁。"""
        # path：认证所有者的固定锁位；调用者必须使它与安全凭据槽的作用域一致。
        self.path = path
        # timeout：本机争抢的单调时钟等待上限，单位秒；不等于远端撤销期限。
        self.timeout = timeout
        # busy_error：固定脱敏忙碌错误；不能使用凭据或网络响应正文。
        self.busy_error = busy_error
        # file：本次上下文拥有的 OS 句柄；异常与正常退出都负责关闭。
        self.file = None

    def __enter__(self):
        """先建固定长度锁位，再有界争抢；失败关闭句柄并保留原业务异常。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"\0")
            self.file.flush()
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                self.file.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        raise self.busy_error from None
                    time.sleep(0.025)
        except BaseException:
            self.file.close()
            self.file = None
            raise

    def __exit__(self, *_):
        """只释放本上下文持有的锁，finally 保证句柄闭合。"""
        if self.file is None:
            return
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None
