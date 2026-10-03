"""本机 HTTP 入站与 Exact Agent 服务装配。
固定静态资源与 API 路由，验证 loopback Host/Origin，限制请求体；认证秘钥不进入产品 JSON，供应商执行由后台 Driver 承担。"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import socket
from typing import Any
from urllib.parse import quote, urlparse, parse_qs
import webbrowser

from . import __version__
from .agent_runtime import AgentRuntime
from .auth import ChatGPTAuthManager
from .providers import create_provider
from .runtime import MythRuntime
from .web_workspace import ConversationWebService


# ASSET_DIR：已打包静态资源的固定目录；HTTP 不接受任意本机路径。
ASSET_DIR = Path(__file__).with_name("webui")


# Exact Agent HTTP 门面；只保存线程管理信息，真实 Run 状态由 Runtime 读取。
class AgentWebService:
    # 保存本机后台 Driver 管理信息并装配 Conversation 门面；HTTP 对象不拥有持久 Run 生命周期。
    def __init__(self, root: str | Path) -> None:
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = Path(root).resolve()
        # _active：本进程后台 Run 集；仅防止重复线程，持久 Lease/锁另行保证接管边界。
        self._active: set[str] = set()
        # _lock：本实例线程互斥锁；不能代替跨进程锁或 SQLite 事务。
        self._lock = threading.Lock()
        # workspace：Conversation 产品装配对象；连接仓储、执行、Control 和长期状态。
        self.workspace = ConversationWebService(self.root)
        # chatgpt_auth：Myth 独立账号认证管理器；只用本应用颁发的客户端身份。
        self.chatgpt_auth = ChatGPTAuthManager(self.root)

    # 按明确 API 配置装配供应商；认证不从用户项目文件获取。
    def _provider(self, payload: dict[str, Any]):
        return create_provider(
            str(payload.get("provider") or "ollama"),
            ollama_base_url=str(payload.get("ollama_url") or "http://127.0.0.1:11434"),
            runtime_root=str(self.root),
        )

    # 在事务外检查连接，返回可公开状态；检查不创建 Run 或消耗业务 Ticket。
    def provider_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = self._provider(payload).check()
        return {
            "provider_id": status.provider_id,
            "ready": status.ready,
            "auth_type": status.auth_type,
            "details": status.details or {},
        }

    # 返回脱敏账号状态和目录；token 不进入 HTTP JSON。
    def chatgpt_status(self) -> dict[str, Any]:
        return {
            "status": self.chatgpt_auth.status().serializable(),
            "profiles": self.chatgpt_auth.profiles(),
        }

    # 创建限时登录挑战并返回固定 loopback callback 的认证入口。
    def chatgpt_begin(
        self, redirect_uri: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.chatgpt_auth.begin_login(
            redirect_uri, profile_id=payload.get("profile_id") or None
        )

    # 把回调参数交独立认证管理器校验，响应只含脱敏状态。
    def chatgpt_complete(self, query: str) -> dict[str, Any]:
        status = self.chatgpt_auth.complete_callback(parse_qs(query))
        return status.serializable()

    # 显式执行远端撤销尝试及本机清理，返回各步事实；网络异常不伪造远端成功。
    def chatgpt_logout(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.chatgpt_auth.logout(payload.get("profile_id") or None)

    # 切换用户明确选择的现有认证 profile；不扩大 scope。
    def chatgpt_select(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(payload.get("profile_id") or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required")
        return self.chatgpt_auth.select_profile(profile_id).serializable()

    # 读取有界 Run 列表供产品/CLI 展示；这是历史投影，不重新驱动任何 Run。
    def list_runs(self) -> list[dict[str, Any]]:
        with MythRuntime(self.root) as runtime:
            return AgentRuntime(runtime).list_runs()

    # 读取当前持久事实并生成状态投影；不得把模型 claim 当作已执行或已验收。
    def status(self, run_id: str) -> dict[str, Any]:
        with MythRuntime(self.root) as runtime:
            result = AgentRuntime(runtime).status(run_id)
        with self._lock:
            result["driver_active"] = run_id in self._active
        return result

    # 从保存的 Run 恢复固定供应商/模型配置；客户端不能用新 payload 偷换在途请求。
    def _fixed_provider_payload(self, run_id):
        agent = self.status(run_id)["agent"]
        return {
            **agent["provider_options"],
            "provider": agent["provider_id"],
            "model": agent["model_id"],
        }

    # 在本机后台管理 Exact Run；具体过程仍经过执行锁和持久恢复。
    def _spawn(
        self, run_id: str, payload: dict[str, Any], *, resume_text: str | None = None
    ) -> None:
        with self._lock:
            if run_id in self._active:
                raise RuntimeError("run is already active in this web process")
            self._active.add(run_id)

        # 在线程独立 Runtime 中运行固定 Exact 用例，finally 清理本机 active；错误保留在持久状态。
        def worker() -> None:
            try:
                provider = self._provider(payload)
                with MythRuntime(self.root) as runtime:
                    agent = AgentRuntime(runtime)
                    if resume_text is None:
                        result = agent.run(run_id, provider)
                    else:
                        result = agent.resume(
                            run_id,
                            provider,
                            resume_text,
                            question_id=payload.get("question_id"),
                        )

                    # 正常返回必须对应持久让出状态；仍是 RUNNING 时安全重入，再把无法推进的状态显式收束为 UNKNOWN。
                    if result["agent"]["status"] == "RUNNING":
                        result = agent.run(run_id, provider)
                    if result["agent"]["status"] == "RUNNING":
                        agent.repository.block(
                            run_id,
                            "UNKNOWN",
                            "web driver returned without yielding a durable non-RUNNING state",
                        )
            except Exception as exc:
                with MythRuntime(self.root) as runtime:
                    AgentRuntime(runtime).repository.block(
                        run_id, "UNKNOWN", f"{type(exc).__name__}: {exc}"
                    )
            finally:
                with self._lock:
                    self._active.discard(run_id)

        threading.Thread(target=worker, name=f"myth-{run_id[:16]}", daemon=True).start()

    # 校验明确允许文件和固定验收后创建 Exact Run，提交后启动后台执行。
    def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = str(payload.get("goal") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not goal:
            raise ValueError("goal is required")
        if not model:
            raise ValueError("model is required")
        provider = self._provider(payload)
        check = provider.check()
        if not check.ready:
            raise RuntimeError(
                "provider is not ready: "
                + json.dumps(check.details or {}, ensure_ascii=False)
            )

        raw_files = payload.get("files") or []
        if not isinstance(raw_files, list):
            raise ValueError("files must be an array")
        files = tuple(
            Path(str(item)).expanduser().resolve()
            for item in raw_files
            if str(item).strip()
        )
        if not files:
            raise ValueError("at least one explicit allowed file is required")

        max_steps = payload.get("max_steps", 6)
        max_output_tokens = payload.get("max_output_tokens", 1024)
        thinking_value = payload.get("thinking")
        thinking = str(thinking_value).strip() if thinking_value else None

        with MythRuntime(self.root) as runtime:
            run_id = AgentRuntime(runtime).create_run(
                goal=goal,
                provider=provider,
                model=model,
                allowed_files=files,
                max_steps=max_steps,
                max_output_tokens=max_output_tokens,
                thinking=thinking,
                request_id=payload.get("request_id"),
                acceptance=payload.get("acceptance"),
                provider_options={
                    "ollama_url": payload.get("ollama_url", "http://127.0.0.1:11434")
                },
            )
        existing = self.status(run_id)
        if existing["agent"]["status"] == "RUNNING" and not existing["driver_active"]:
            self._spawn(run_id, self._fixed_provider_payload(run_id))
        return {"run_id": run_id, "status": existing["agent"]["status"]}

    # 消费明确待答问题身份及用户文本，继续原 Run；不创建替代工作绕过 UNKNOWN。
    def resume(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        current = self.status(run_id)["agent"]
        if (
            current["status"] != "WAITING_USER"
            or payload.get("question_id") != current["question_id"]
        ):
            raise ValueError("answer must match the current pending question_id")
        self._spawn(
            run_id,
            {
                **self._fixed_provider_payload(run_id),
                "question_id": current["question_id"],
            },
            resume_text=text,
        )
        return {"run_id": run_id, "status": "RUNNING"}

    # 显式重新驱动已有可恢复 Run，先按执行事实恢复而不是盲重发。
    def advance(self, run_id):
        status = self.status(run_id)["agent"]["status"]
        if status not in {"RUNNING", "UNKNOWN"}:
            raise ValueError("only interrupted or uncertain runs can be continued")
        self._spawn(run_id, self._fixed_provider_payload(run_id))
        return {"run_id": run_id, "status": "RUNNING"}

    # 记录停止未来工作的意图/状态；已发出效果仍按实际结果结算。
    def cancel(self, run_id):
        with MythRuntime(self.root) as runtime:
            return AgentRuntime(runtime).cancel(run_id)

    # 创建确定性本地演示任务；无真实模型质量证明。
    def demo(self):
        from .demo import create_demo

        with MythRuntime(self.root) as runtime:
            run_id, _ = create_demo(runtime)
        self._spawn(run_id, {"provider": "scripted"})
        return {"run_id": run_id, "status": "RUNNING"}

    # 取得已获可信验收的交付对象；缺少报告或摘要不允许下载成已验收产物。
    def artifact(self, run_id, index):
        with MythRuntime(self.root) as runtime:
            status = AgentRuntime(runtime).status(run_id)
            if status["agent"]["status"] != "SUCCEEDED" or not status["delivery"]:
                raise PermissionError("only verified deliveries can be downloaded")
            files = status["acceptance"]["files"]
            if index < 0 or index >= len(files):
                raise KeyError(index)
            item = files[index]
            return Path(item["path"]).name, runtime.objects.get(item["expected_digest"])


# 编码中文 JSON 响应；调用方只能传递可公开投影。
def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


# 把服务门面装配为 loopback HTTP Handler；路由不是 Runtime 状态所有者。
def make_handler(service: AgentWebService):
    # 固定 loopback 路由的 HTTP 入站适配器；只解析有界参数/返回投影，业务状态仍归仓储与用例。
    class Handler(BaseHTTPRequestHandler):
        # server_version：HTTP Server 响应中的应用标识；不属于业务协议版本。
        server_version = f"MythWeb/{__version__}"

        # 输出常规脱敏访问路径；认证回调路径敏感参数不记录。
        def log_message(self, format: str, *args: object) -> None:
            # 认证回调 URL 含单次 code/state，访问日志仅记录路径，不能记录 query。
            safe_path = urlparse(self.path).path
            print(f"[myth-web] {self.address_string()} - {self.command} {safe_path}")

        # 发送固定内容/长度及安全响应头；状态数据必须先由用例生成。
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        # 将可公开数据编码为 JSON HTTP 响应；不直接序列化认证秘钥。
        def _json(self, status: int, value: Any) -> None:
            self._send(status, _json_bytes(value), "application/json; charset=utf-8")

        # 限制请求体大小和 JSON 形状后返回参数；解析成功不意味着业务准入成功。
        def _read_json(self) -> dict[str, Any]:
            if (
                self.headers.get("Content-Type", "").split(";")[0].strip()
                != "application/json"
            ):
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length") or 0)
            limit = (
                7_000_000
                if urlparse(self.path).path == "/api/workspace/documents"
                else 1_000_000
            )
            if length <= 0 or length > limit:
                raise ValueError(
                    f"request body must be between 1 byte and {limit} bytes"
                )
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        # 只从固定包目录返回已声明静态资源，不能按请求任意读取本机文件。
        def _asset(self, name: str, content_type: str) -> None:
            path = ASSET_DIR / name
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "asset not found"})
                return
            self._send(HTTPStatus.OK, path.read_bytes(), content_type)

        # 按白名单分派静态/状态/产物和认证回调；Host 先校验，下载仍核对真实身份。
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/auth/callback":
                    self._check_host()
                    service.chatgpt_complete(urlparse(self.path).query)
                    body = b"Myth is connected to ChatGPT. You can close this window and return to Myth."
                    self._send(HTTPStatus.OK, body, "text/plain; charset=utf-8")
                    return
                self._check_origin()
                if path == "/api/auth/chatgpt/status":
                    self._json(HTTPStatus.OK, service.chatgpt_status())
                    return
                if path == "/api/workspace" or path.startswith("/api/workspace/"):
                    parts = (
                        path.removeprefix("/api/workspace").strip("/").split("/")
                        if path != "/api/workspace"
                        else []
                    )
                    if (
                        len(parts) == 2
                        and parts[0] == "artifacts"
                        or len(parts) == 3
                        and parts[0] in {"messages", "sessions"}
                        and parts[2] == "download"
                    ):
                        name, data = (
                            service.workspace.artifact(parts[1])
                            if parts[0] == "artifacts"
                            else service.workspace.export(parts[0], parts[1])
                        )
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header(
                            "Content-Disposition",
                            "attachment; filename*=UTF-8''" + quote(name),
                        )
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    self._json(
                        HTTPStatus.OK,
                        service.workspace.get(
                            parts, parse_qs(urlparse(self.path).query)
                        ),
                    )
                    return
                if path == "/":
                    self._asset("index.html", "text/html; charset=utf-8")
                    return
                if path == "/app.css":
                    self._asset("app.css", "text/css; charset=utf-8")
                    return
                if path == "/app.js":
                    self._asset("app.js", "text/javascript; charset=utf-8")
                    return
                if path == "/inspector.js":
                    self._asset("inspector.js", "text/javascript; charset=utf-8")
                    return
                if path == "/goals.js":
                    self._asset("goals.js", "text/javascript; charset=utf-8")
                    return
                if path == "/api/runs":
                    self._json(HTTPStatus.OK, {"runs": service.list_runs()})
                    return
                if path.startswith("/api/runs/"):
                    parts = path.removeprefix("/api/runs/").split("/")
                    if len(parts) == 3 and parts[1] == "artifacts":
                        name, data = service.artifact(parts[0], int(parts[2]))
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header(
                            "Content-Disposition",
                            "attachment; filename*=UTF-8''" + quote(name),
                        )
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    run_id = path.removeprefix("/api/runs/").strip("/")
                    if not run_id or "/" in run_id:
                        raise ValueError("invalid run id")
                    self._json(HTTPStatus.OK, service.status(run_id))
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except PermissionError as exc:
                self._json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
            except Exception as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"{type(exc).__name__}: {exc}"},
                )

        # 先校验 Host/Origin 和有界 JSON，再调用对应写用例；异常按合同回给页面。
        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                self._check_origin()
                payload = self._read_json()
                if path == "/api/auth/chatgpt/start":
                    redirect_uri = (
                        f"http://127.0.0.1:{self.server.server_port}/auth/callback"
                    )
                    self._json(
                        HTTPStatus.OK, service.chatgpt_begin(redirect_uri, payload)
                    )
                    return
                if path == "/api/auth/chatgpt/logout":
                    self._json(HTTPStatus.OK, service.chatgpt_logout(payload))
                    return
                if path == "/api/auth/chatgpt/select":
                    self._json(HTTPStatus.OK, service.chatgpt_select(payload))
                    return
                if path.startswith("/api/workspace/"):
                    parts = path.removeprefix("/api/workspace/").strip("/").split("/")
                    self._json(HTTPStatus.OK, service.workspace.post(parts, payload))
                    return
                if path == "/api/demo":
                    self._json(HTTPStatus.ACCEPTED, service.demo())
                    return
                if path == "/api/provider/check":
                    self._json(HTTPStatus.OK, service.provider_check(payload))
                    return
                if path == "/api/runs":
                    self._json(HTTPStatus.ACCEPTED, service.start_run(payload))
                    return
                if path.startswith("/api/runs/") and path.endswith("/resume"):
                    run_id = (
                        path.removeprefix("/api/runs/")
                        .removesuffix("/resume")
                        .strip("/")
                    )
                    self._json(HTTPStatus.ACCEPTED, service.resume(run_id, payload))
                    return
                if path.startswith("/api/runs/") and path.endswith("/continue"):
                    self._json(HTTPStatus.ACCEPTED, service.advance(path.split("/")[3]))
                    return
                if path.startswith("/api/runs/") and path.endswith("/cancel"):
                    self._json(HTTPStatus.OK, service.cancel(path.split("/")[3]))
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, PermissionError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
            except Exception as exc:
                self._json(
                    HTTPStatus.CONFLICT,
                    {"error": f"{type(exc).__name__}: {exc}"},
                )

        # 仅接受本机绑定的 Host，阻止跨主机解释入站请求。
        def _check_host(self):
            host = self.headers.get("Host", "")
            parsed = urlparse("http://" + host)
            if (
                parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.port != self.server.server_port
            ):
                raise PermissionError("Host must match this local server")

        # 验证写入请求 Origin 为同本机服务；不是多用户权限系统。
        def _check_origin(self):
            self._check_host()
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                raise PermissionError("cross-origin access is not allowed")

    return Handler


# 装配 loopback Web 与后台 Goal 检查线程；服务退出停止调度检查，已发出效果保留真实收据。
def serve(
    root: str | Path = ".",
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "Myth Web binds to loopback only; use a reverse proxy after adding authentication"
        )
    service = AgentWebService(root)
    server_type = ThreadingHTTPServer
    if ":" in host:

        # IPv6 loopback 的入站适配器；只替换地址族，复用相同 Host/Origin 和业务 Handler。
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            # 地址族固定为 IPv6；不会因此放开公网绑定范围。
            address_family = socket.AF_INET6

        server_type = IPv6ThreadingHTTPServer
    server = server_type((host, port), make_handler(service))
    display_host = f"[{host}]" if ":" in host else host
    url = f"http://{display_host}:{server.server_port}/"
    print(f"Myth Web: {url}")
    service.workspace.start_scheduler()
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.workspace.stop_scheduler()
        server.server_close()
