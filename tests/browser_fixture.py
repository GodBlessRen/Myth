"""浏览器验收的真实 HTTP/SQLite 夹具；固定模型与公开目录，不读取真实账号。"""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

from myth.adapters.model_catalog import PublicModelCatalog
from myth.models import ProviderStatus
from myth.runtime import MythRuntime
from myth.web import AgentWebService, make_handler
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from myth.web_assets import PUBLIC_ASSETS
from test_workspace import ChatProvider, decision


class FixtureProvider(ChatProvider):
    """只替换外部模型协议；准入、收据、费用账本和状态迁移仍走生产实现。"""

    def __init__(self, provider_id="ollama", outputs=None):
        """夹具配置与调用记录仅在测试进程存活，不接触系统凭据。"""
        super().__init__(outputs)
        self.provider_id = provider_id

    def check(self):
        """两个固定模型分别无可调推理、有原生推理档位，不代表远端目录。"""
        profiles = {
            name: {"id": name, "context_window": 32768, "max_output_tokens": 8192,
                   "temperature": {"supported": self.provider_id not in {"anthropic", "claude_oauth"}, "min": 0, "max": 2}}
            for name in ("review-model", "review-reasoning")
        }
        profiles["review-reasoning"]["reasoning"] = {
            "kind": "levels", "levels": ["low", "medium", "high"],
            "default": "medium", "off": "none", "source": "fixture",
        }
        return ProviderStatus(self.provider_id, True, "fixture", {
            "models": list(profiles), "model_capabilities": profiles,
        })

    def invoke(self, request):
        """短暂固定等待使真实 Driver 的在途状态可观察，不冒充供应商首 Token 时间。"""
        text = "\n".join(message.content for message in request.messages)
        time.sleep(3 if "等待反馈" in text else 0.1)
        return super().invoke(request)


class FixtureWebService(ConversationWebService):
    """只在专用测试启动入口接入固定供应商；业务端点和仓储保持真实。"""

    def provider(self, settings):
        """按固定设置保留提供方身份，禁止测试过程中请求远端服务。"""
        return FixtureProvider(settings["provider"])

    def connection(self, payload=None, *, force=False):
        """固定外部目录协议，不通过连接检查取得任何额外业务权限。"""
        status = self.provider(payload or self._use("settings")).check()
        return {"ready": status.ready, "provider": status.provider_id, "details": status.details}


def seed(root):
    """通过生产仓储和应用循环生成可读状态；租约过期仅注入时钟窗口。"""
    ids = {}
    with MythRuntime(root) as runtime:
        work = Workspace(runtime)
        repo = work.repository
        repo.save_settings({"provider": "ollama", "model": "review-model", "num_ctx": 32768, "max_steps": 12})
        project_root = root / "project"
        project_root.mkdir()
        (project_root / "README.md").write_text("# 研究工作区\n记录执行、记忆与验收证据。\n", encoding="utf-8")
        project = repo.create_project({"name": "Agent 研究笔记", "root": str(project_root),
            "description": "证据、实验与实现放在同一个工作区。"})
        ids["project"] = project["id"]
        repo.knowledge.import_document({"title": "执行与恢复设计", "project_id": project["id"],
            "content": "Goal 跨会话保存工作状态。Ticket 先于外部效果，Receipt 记录真实结果。UNKNOWN 先核对，不能盲目重放。"})
        goal = work.personal.create_goal("完成第一轮架构复核", "核对执行、记忆和验收边界，保留可追溯证据。")
        ids["goal"] = goal["goal_id"]
        cases = [
            ("completed", "执行边界复核", "整理执行与恢复的关键边界，并生成一份复核笔记。", [
                decision("tool_call", "artifact.write", {"path": "reports/review.md", "content": "# 架构复核\n\nTicket 是开始授权，Receipt 是执行事实。UNKNOWN 先核对，不盲目重放。\n"}),
                decision(claim="已生成复核笔记，保留了三个关键边界。\n\nTicket 先于外部效果，Receipt 保存真实结果；UNKNOWN 需要核对；回答结束不等于验收通过。\n\n文档可从附件下载，尚未进行独立语义验收。"),
            ]),
            ("waiting", "等待实验范围确认", "为下一轮实验选择一个明确的比较范围。", [decision("ask_user", question="这轮先比较执行恢复，还是上下文效率？")]),
            ("unknown", "中断后的结果核对", "核对一次模型请求中断后的恢复状态。", None),
        ]
        for key, title, text, outputs in cases:
            sid = repo.create_session(title, project["id"])["id"]
            rid = repo.create_turn(sid, text, "fixture-" + key)["run_id"]
            provider = ChatProvider(outputs)
            if outputs is None:
                def uncertain(request):
                    """仅模拟已派发但未确认的外部结果，生产恢复必须保留 UNKNOWN。"""
                    raise RuntimeError("fixture interrupted after dispatch")
                provider.invoke = uncertain
            work.run(rid, provider)
            ids[key], ids[key + "_run"] = sid, rid
        for key, title in (("interrupted", "准备继续的工作"), ("failed", "失败记录")):
            sid = repo.create_session(title, project["id"])["id"]
            rid = repo.create_turn(sid, "继续核对近期改变的模块。", "fixture-" + key)["run_id"]
            if key == "interrupted":
                repo.claim_driver(rid, "expired-fixture-driver", 6)
                with runtime.store.tx() as db:
                    db.execute("UPDATE workspace_driver_leases SET lease_until=? WHERE run_id=?", (time.time() - 1, rid))
                repo.sweep_expired_driver(rid)
            else:
                repo.block(rid, "FAILED", "验收夹具：已知失败与未知结果分别显示。")
            ids[key], ids[key + "_run"] = sid, rid
    return ids


def main():
    """临时根和所有服务器由当前测试进程拥有；SIGTERM 清理，无真实 OAuth 或外网调用。"""
    out = Path(__file__).resolve().parents[1] / ".work"
    out.mkdir(exist_ok=True)
    parser = argparse.ArgumentParser()
    parser.add_argument('--dynamic-ports', action='store_true', help='Allocate independent loopback listeners')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    catalog = {p: {"models": {m: {"cost": {"input": 1, "output": 3}, "limit": {"output": 8192}}
               for m in ("review-model", "review-reasoning")}} for p in ("openai", "anthropic", "deepseek", "moonshotai")}
    with tempfile.TemporaryDirectory(prefix="myth-browser-") as directory:
        root = Path(directory)
        ids = seed(root / "populated")
        servers = []
        try:
            addresses = {}
            for name, port, sub in (("workflow", 8770, "populated"), ("base", 8772, "populated"), ("empty", 8773, "empty"), ("settings", 8776, "populated"), ("standard", 8769, "standard")):
                service = AgentWebService(root / sub)
                if name != "standard":
                    service.workspace = FixtureWebService(root / sub)
                    service.workspace.model_catalog = PublicModelCatalog(lambda: catalog)
                    service.provider_key_status = lambda: {"providers": []}
                    service._provider = lambda payload: FixtureProvider(payload.get("provider", "ollama"))
                server = ThreadingHTTPServer(("127.0.0.1", 0 if args.dynamic_ports else port), make_handler(service))
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append((server, service))
                addresses[name] = "http://127.0.0.1:" + str(server.server_port)
            source_root = Path(__file__).resolve().parents[1] / "src/myth/webui"
            assets = {url: {"file": filename, "mime": mime, "sha256": hashlib.sha256((source_root / filename).read_bytes()).hexdigest()}
                      for url, (filename, mime) in PUBLIC_ASSETS.items()}
            (out / "browser-fixture.json").write_text(json.dumps({"root": str(root), "ids": ids,
                **addresses, "pid": os.getpid(), "assets": assets,
                "boundary": "real HTTP/SQLite/Runtime; deterministic provider; separately owned loopback listeners"}, ensure_ascii=False), encoding="utf-8")
            print("READY " + json.dumps(addresses), flush=True)
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            for server, service in servers:
                service.workspace.stop_scheduler()
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
