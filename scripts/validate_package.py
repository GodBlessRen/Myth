"""在隔离根核对真实安装 wheel、HTTP 静态资源和计划 API。

运行：python scripts/validate_package.py --package-dir .runtime/wheel-installed
必须从指定安装目录导入；使用真实本机 HTTP/SQLite，不调用模型或登录 OAuth。
通过仅证明包内入口和这些基本产品路径，不证明模型质量。
"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from urllib import request


# 检查导入来源，再开临时工作区和 HTTP 服务；所有资源在 finally 中关闭。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, required=True)
    args = parser.parse_args()
    package_dir = args.package_dir.resolve()
    sys.path.insert(0, str(package_dir))
    import myth
    from myth.web import AgentWebService, make_handler
    from myth.runtime import MythRuntime
    from myth.workspace import Workspace

    if not Path(myth.__file__).resolve().is_relative_to(package_dir):
        raise RuntimeError("import did not use the installed package")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with MythRuntime(root) as runtime:
            Workspace(runtime).repository.save_settings(
                {"provider": "ollama", "model": "package-check"}
            )
        service = AgentWebService(root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        # 经真实 loopback HTTP 发送明确测试参数；不是绕过 Handler 的直接仓储调用。
        def call(path, value=None):
            body = json.dumps(value).encode() if value is not None else None
            with request.urlopen(
                request.Request(
                    base + path, data=body, headers={"Content-Type": "application/json"}
                ),
                timeout=5,
            ) as response:
                return json.load(response)

        try:
            for asset in ("/", "/app.css", "/app.js", "/inspector.js", "/goals.js",
                          "/theme.js", "/reconnect.js", "/statistics.js", "/favicon.svg",
                          "/fonts/myth-sans.woff2", "/fonts/myth-serif.woff2", "/fonts/myth-latin.woff2", "/model-pool.js", "/studio.js", "/choices.js", "/taiji.svg", "/ink-taiji.png"):
                with request.urlopen(base + asset, timeout=5) as response:
                    if response.status != 200 or not response.read():
                        raise RuntimeError(f"missing packaged asset: {asset}")
            session = call(
                "/api/workspace/sessions", {"title": "Installed package check"}
            )
            goal = call("/api/workspace/goals", {"title": "Installed Goal"})
            schedule = call(
                f"/api/workspace/goals/{goal['goal_id']}/schedules",
                {
                    "request_id": "package-smoke",
                    "session_id": session["id"],
                    "prompt": "Future work",
                    "due_at": "2030-01-01T00:00:00Z",
                },
            )
            paused = call(
                f"/api/workspace/schedules/{schedule['schedule_id']}/enabled",
                {"enabled": False},
            )
            if paused["enabled"]:
                raise RuntimeError("timer was not paused")
            if len(call("/api/workspace/schedules")["schedules"]) != 1:
                raise RuntimeError("schedule was not persisted")
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "version": myth.__version__,
                        "import_path": str(myth.__file__),
                        "checks": [
                            "installed import",
                            "HTTP assets",
                            "Goal/session",
                            "schedule persistence/pause",
                        ],
                    },
                    indent=2,
                )
            )
        finally:
            service.workspace.stop_scheduler()
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    main()
