"""认证 OS 锁的真实子进程回归；只操作零字节锁位，不使用任何凭据。

父进程持锁时子进程必须有界拒绝，释放后同一地址可取得；验证范围是本机互斥，
不是系统安全库、公开文件与网络的联合事务。
"""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

from myth.auth.state_lock import AuthStateLock


class AuthStateLockTests(unittest.TestCase):
    """使用当前 Python 和源码路径启动独立进程，避免以线程替身冒充 OS 互斥。"""

    def test_another_process_is_denied_until_owner_releases(self):
        """同地址只有一个所有者；锁超时拒绝，正常退出释放真实句柄。"""
        program = """
from pathlib import Path
import sys
from myth.auth.state_lock import AuthStateLock
try:
    with AuthStateLock(Path(sys.argv[1]), 0.1, RuntimeError('busy')):
        print('acquired')
except RuntimeError:
    print('busy')
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "auth.lock"
            with AuthStateLock(path, 1, RuntimeError("busy")):
                rejected = subprocess.run([sys.executable, "-c", program, str(path)],
                                          env=environment, capture_output=True, text=True, timeout=10)
            accepted = subprocess.run([sys.executable, "-c", program, str(path)],
                                      env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        self.assertEqual(rejected.stdout.strip(), "busy")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "acquired")
