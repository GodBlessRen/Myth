"""本机 Web 的封闭资源合同，由 HTTP 与安装验收共同消费。

只声明公开 URL、包内相对路径与 MIME；不扫目录、不解释用户路径、不拥有业务状态。
例如 /fonts/unknown.woff2 不会因为文件存在就被公开。
"""

from types import MappingProxyType

# 元组与只读映射避免调用方运行时扩大静态路由；新资源在此显式登记。
PUBLIC_ASSETS = MappingProxyType({
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/inspector.js": ("inspector.js", "text/javascript; charset=utf-8"),
    "/goals.js": ("goals.js", "text/javascript; charset=utf-8"),
    "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/reconnect.js": ("reconnect.js", "text/javascript; charset=utf-8"),
    "/statistics.js": ("statistics.js", "text/javascript; charset=utf-8"),
    "/model-pool.js": ("model-pool.js", "text/javascript; charset=utf-8"),
    "/studio.js": ("studio.js", "text/javascript; charset=utf-8"),
    "/choices.js": ("choices.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/logo.svg": ("logo.svg", "image/svg+xml"),
    "/logo-dark.svg": ("logo-dark.svg", "image/svg+xml"),
    "/logo-mono.svg": ("logo-mono.svg", "image/svg+xml"),
    "/logo-16.svg": ("logo-16.svg", "image/svg+xml"),
    "/logo-32.svg": ("logo-32.svg", "image/svg+xml"),
    "/fonts/myth-sans.woff2": ("fonts/myth-sans.woff2", "font/woff2"),
    "/fonts/myth-serif.woff2": ("fonts/myth-serif.woff2", "font/woff2"),
    "/fonts/myth-latin.woff2": ("fonts/myth-latin.woff2", "font/woff2"),
})
