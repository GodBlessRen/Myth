"""Local-only web surface for Myth P3.

The server binds to loopback by default and exposes no shell, repository write
API, credential endpoint, or arbitrary file browser. Agent work runs in daemon
threads so the browser can poll durable state immediately.
"""

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

from .agent_runtime import AgentRuntime
from .providers import create_provider
from .runtime import MythRuntime
from .web_workspace import ConversationWebService


ASSET_DIR = Path(__file__).with_name("webui")


class AgentWebService:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self.workspace = ConversationWebService(self.root)

    @staticmethod
    def _provider(payload: dict[str, Any]):
        return create_provider(
            str(payload.get("provider") or "ollama"),
            ollama_base_url=str(payload.get("ollama_url") or "http://127.0.0.1:11434"),
            pi_command=str(payload.get("pi_command") or "pi"),
        )

    def provider_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = self._provider(payload).check()
        return {
            "provider_id": status.provider_id,
            "ready": status.ready,
            "auth_type": status.auth_type,
            "details": status.details or {},
        }

    def list_runs(self) -> list[dict[str, Any]]:
        with MythRuntime(self.root) as runtime:
            return AgentRuntime(runtime).list_runs()

    def status(self, run_id: str) -> dict[str, Any]:
        with MythRuntime(self.root) as runtime:
            result = AgentRuntime(runtime).status(run_id)
        with self._lock:
            result["driver_active"] = run_id in self._active
        return result

    def _fixed_provider_payload(self, run_id):
        agent = self.status(run_id)["agent"]
        return {**agent["provider_options"], "provider": agent["provider_id"], "model": agent["model_id"]}

    def _spawn(self, run_id: str, payload: dict[str, Any], *, resume_text: str | None = None) -> None:
        with self._lock:
            if run_id in self._active:
                raise RuntimeError("run is already active in this web process")
            self._active.add(run_id)

        def worker() -> None:
            try:
                provider = self._provider(payload)
                with MythRuntime(self.root) as runtime:
                    agent = AgentRuntime(runtime)
                    if resume_text is None:
                        agent.run(run_id, provider)
                    else:
                        agent.resume(run_id, provider, resume_text, question_id=payload.get("question_id"))
            except Exception as exc:
                with MythRuntime(self.root) as runtime:
                    AgentRuntime(runtime).repository.block(run_id, "UNKNOWN", f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._active.discard(run_id)

        threading.Thread(target=worker, name=f"myth-{run_id[:16]}", daemon=True).start()

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
                "provider is not ready: " + json.dumps(check.details or {}, ensure_ascii=False)
            )

        raw_files = payload.get("files") or []
        if not isinstance(raw_files, list):
            raise ValueError("files must be an array")
        files = tuple(Path(str(item)).expanduser().resolve() for item in raw_files if str(item).strip())
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
                provider_options={"ollama_url": payload.get("ollama_url", "http://127.0.0.1:11434"), "pi_command": payload.get("pi_command", "pi")},
            )
        existing = self.status(run_id)
        if existing["agent"]["status"] == "RUNNING" and not existing["driver_active"]:
            self._spawn(run_id, self._fixed_provider_payload(run_id))
        return {"run_id": run_id, "status": existing["agent"]["status"]}

    def resume(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        current = self.status(run_id)["agent"]
        if current["status"] != "WAITING_USER" or payload.get("question_id") != current["question_id"]:
            raise ValueError("answer must match the current pending question_id")
        self._spawn(run_id, {**self._fixed_provider_payload(run_id), "question_id": current["question_id"]}, resume_text=text)
        return {"run_id": run_id, "status": "RUNNING"}

    def advance(self, run_id):
        status = self.status(run_id)["agent"]["status"]
        if status not in {"RUNNING", "UNKNOWN"}:
            raise ValueError("only interrupted or uncertain runs can be continued")
        self._spawn(run_id, self._fixed_provider_payload(run_id))
        return {"run_id": run_id, "status": "RUNNING"}

    def cancel(self, run_id):
        with MythRuntime(self.root) as runtime:
            return AgentRuntime(runtime).cancel(run_id)

    def demo(self):
        from .demo import create_demo
        with MythRuntime(self.root) as runtime:
            run_id, _ = create_demo(runtime)
        self._spawn(run_id, {"provider": "scripted"})
        return {"run_id": run_id, "status": "RUNNING"}

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


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def make_handler(service: AgentWebService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MythWeb/0.13"

        def log_message(self, format: str, *args: object) -> None:
            # Keep local logs useful while avoiding request bodies and credentials.
            print(f"[myth-web] {self.address_string()} - {format % args}")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, _json_bytes(value), "application/json; charset=utf-8")

        def _read_json(self) -> dict[str, Any]:
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length") or 0)
            limit=7_000_000 if urlparse(self.path).path=="/api/workspace/documents" else 1_000_000
            if length <= 0 or length > limit:
                raise ValueError(f"request body must be between 1 byte and {limit} bytes")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _asset(self, name: str, content_type: str) -> None:
            path = ASSET_DIR / name
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "asset not found"})
                return
            self._send(HTTPStatus.OK, path.read_bytes(), content_type)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                self._check_origin()
                if path == "/api/workspace" or path.startswith("/api/workspace/"):
                    parts=path.removeprefix("/api/workspace").strip("/").split("/") if path!="/api/workspace" else []
                    if len(parts)==2 and parts[0]=="artifacts" or len(parts)==3 and parts[0] in {"messages","sessions"} and parts[2]=="download":
                        name,data=service.workspace.artifact(parts[1]) if parts[0]=="artifacts" else service.workspace.export(parts[0],parts[1])
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type","application/octet-stream")
                        self.send_header("Content-Length",str(len(data)))
                        self.send_header("X-Content-Type-Options","nosniff")
                        self.send_header("Cache-Control","no-store")
                        self.send_header("Content-Disposition","attachment; filename*=UTF-8''"+quote(name))
                        self.end_headers();self.wfile.write(data);return
                    self._json(HTTPStatus.OK,service.workspace.get(parts,parse_qs(urlparse(self.path).query)));return
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
                        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
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

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                self._check_origin()
                payload = self._read_json()
                if path.startswith("/api/workspace/"):
                    parts=path.removeprefix("/api/workspace/").strip("/").split("/")
                    self._json(HTTPStatus.OK,service.workspace.post(parts,payload));return
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
                    run_id = path.removeprefix("/api/runs/").removesuffix("/resume").strip("/")
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

        def _check_origin(self):
            host = self.headers.get("Host", "")
            parsed = urlparse("http://" + host)
            if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.port != self.server.server_port:
                raise PermissionError("Host must match this local server")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + host:
                raise PermissionError("cross-origin access is not allowed")

    return Handler


def serve(
    root: str | Path = ".",
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Myth Web binds to loopback only; use a reverse proxy after adding authentication")
    service = AgentWebService(root)
    server_type = ThreadingHTTPServer
    if ":" in host:
        class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6
        server_type = IPv6ThreadingHTTPServer
    server = server_type((host, port), make_handler(service))
    display_host = f"[{host}]" if ":" in host else host
    url = f"http://{display_host}:{server.server_port}/"
    print(f"Myth Web: {url}")
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
