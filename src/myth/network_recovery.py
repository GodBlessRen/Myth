"""断连恢复的纯规则。
定义检查退避和可证明未派发的网络错误；不睡眠、不访问网络、不授予重发权限，持久等待由 Run 仓储拥有。"""

import errno
import socket


# 按连续失败次数返回秒数；第七次起每分钟一次，先限指数避免长期离线的大整数增长。
def reconnect_delay(failures: int) -> int:
    if type(failures) is not int or failures < 1:
        raise ValueError("failures must be a positive integer")
    return min(60, 1 << min(failures - 1, 6))


# 仅 DNS/明确拒连/无网络或路由能证明 HTTP 尚未送达；超时、重置、半截响应均不能据此重发。
def is_pre_dispatch_disconnect(reason) -> bool:
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError)) or (
        isinstance(reason, OSError)
        and reason.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}
    )
