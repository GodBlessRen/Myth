"""认证外圈的受限 HTTP 传输。
固定凭据接收端、不跟随重定向，并限制响应大小；只返回允许公开的错误码，不能保存请求秘钥。
"""

from urllib import request

# 凭据响应的内存上限，单位字节；流式正文另按事件累计检查。
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# 允许公开和用于恢复分支的协议错误码；未知远端字符串可能回显 token，必须折叠。
PUBLIC_ERROR_CODES = frozenset({
    "invalid_grant", "invalid_refresh_token", "token_expired",
    "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused",
    "invalid_client", "invalid_request", "invalid_scope", "access_denied",
    "temporarily_unavailable", "server_error", "invalid_api_key",
    "insufficient_quota", "rate_limit_exceeded", "context_length_exceeded",
    "subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable",
    "subscription_sharing_not_enabled", "model_not_found",
})


# 所有带 Bearer/表单秘钥的请求都禁止自动重定向，避免 urllib 将认证头复制到其他主机。
class _NoRedirect(request.HTTPRedirectHandler):
    # 返回 None 让 urllib 抛出 HTTPError；不构造下一跳请求，不传播认证头或表单。
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# 保留系统代理/TLS 验证；每次独立 opener 不修改全局 urllib，不能自动重试已派发调用。
def open_credential_request(req, *, timeout):
    return request.build_opener(_NoRedirect()).open(req, timeout=timeout)


# 只读上限加一字节以识别超限；解析错误不能把收到的字节放进公开异常。
def read_bounded(response, limit=MAX_RESPONSE_BYTES):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise RuntimeError("HTTP response exceeds the configured byte limit")
    return raw


# 未知错误只给固定兜底值，不能用正则格式检查代替对远端内容的信任判断。
def public_error_code(value, fallback):
    return value if isinstance(value, str) and value in PUBLIC_ERROR_CODES else fallback


# 对准备持久化的响应移除敏感字段，并遮蔽供应商回显的当前请求秘钥；不修改原始对象。
def redact_response(value, token):
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, list):
        return [redact_response(item, token) for item in value]
    if isinstance(value, dict):
        return {
            redact_response(key, token): redact_response(item, token)
            for key, item in value.items()
            if key.lower() not in {
                "access_token", "refresh_token", "id_token", "authorization",
                "code_verifier", "api_key", "client_secret",
            }
        }
    return value
