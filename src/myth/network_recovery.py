"""断连恢复的纯规则。
定义检查退避和可证明未派发的网络错误；不睡眠、不访问网络、不授予重发权限，持久等待由 Run 仓储拥有。"""

import errno
import socket


# 按连续失败次数返回秒数；第七次起每分钟一次，先限指数避免长期离线的大整数增长。
def reconnect_delay(failures: int) -> int:
    if type(failures) is not int or failures < 1:
        raise ValueError("failures must be a positive integer")
    return min(60, 1 << min(failures - 1, 6))


# 由传输的 connect 阶段签发的固定证据；不包含地址、请求头、异常正文或供应商凭据。
class ConnectionNotDispatched(OSError):
    # 只表达尚未建立连接；调用者不能凭任意同名 OSError 推定请求没有发送。
    def __init__(self):
        super().__init__("Connection could not be established before dispatch")


# 这些原因只有在 connect 阶段观察到才允许签发上述证据；发送/读响应阶段同名错误不可重放。
def is_connection_failure(reason) -> bool:
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError)) or (
        isinstance(reason, OSError)
        and reason.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}
    )


# 普通 URLError 的错误类型并不包含发送进度；只接受连接层的明确阶段证据。
def is_pre_dispatch_disconnect(reason) -> bool:
    return isinstance(reason, ConnectionNotDispatched)
