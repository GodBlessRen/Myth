"""浏览器回归专用 loopback 服务。
只替换 Provider 传输：HTTP、SQLite、Turn、Driver、Receipt 和 UI 使用真实实现。
固定模型目录与输出不能作为真实 Provider、OAuth 或模型质量证据。
"""

from __future__ import annotations

import argparse
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import time

from myth.models import ModelResult, ProviderStatus
from myth.web import AgentWebService, make_handler
from myth.web_workspace import ConversationWebService


# 只提供确定性传输边界；用户文本仍经真实上下文与 Runtime 准入。
class BrowserFixtureProvider:
    # 秒：仅验收服务延长真实等待窗口，便于截图在途反馈，不改变生产调用。
    delay_seconds = 0.35
    # 保存目录所属 Provider 身份，避免混用品牌能力。
    def __init__(self, provider_id: str) -> None:
        # provider_id：固定回归目录身份，不代表真实远端连接。
        self.provider_id = provider_id

    # 返回可控目录，分别覆盖可调 reasoning 和缺少 reasoning 两种表单。
    def check(self):
        models = ["review-model", "review-reasoning"]
        return ProviderStatus(self.provider_id, True, details={
            "models": models,
            "model_capabilities": {
                models[0]: {"context_window": 32768, "max_output_tokens": 8192, "source": "browser regression fixture"},
                models[1]: {"context_window": 65536, "max_output_tokens": 8192, "reasoning": {"levels": ["low", "medium", "high"], "off": "none", "default": "medium"}, "source": "browser regression fixture"},
            },
        })

    # 固定回答在真实 Driver 中保存收据；停顿仅用于观察在途输入禁用和运行状态。
    def invoke(self, request):
        time.sleep(self.delay_seconds)
        text = "已收到你的任务。\n\n可以先明确预期结果，再整理资料和执行步骤。当前对话会保留在工作区，你可以继续补充要求。"
        decision = json.dumps({
            "decision_type": "request_completion", "reason": "浏览器回归固定回答",
            "capability_id": "", "arguments_json": "{}", "question": "",
            "missing_info_category": "", "claim": text, "goal_coverage": "answer",
            "evidence_refs": [], "remaining": [],
        }, ensure_ascii=False)
        return ModelResult(decision, {"model_calls": 1, "input_tokens": 164, "output_tokens": 62, "cached_input_tokens": 0}, {"text": text, "status": "completed"})


# 回归服务只替换传输目录，其他产品与持久执行均继承真实门面。
class BrowserFixtureWorkspace(ConversationWebService):
    def __init__(self, root):
        """固定公开价格目录替身，浏览器回归不访问真实模型或联网计费。"""
        super().__init__(root)
        from myth.adapters.model_catalog import PublicModelCatalog
        self.model_catalog = PublicModelCatalog(loader=lambda: {key: {"models": {
            model: {"cost": {"input": 1, "output": 2}, "limit": {"output": 8192}}
            for model in ("review-model", "review-reasoning")
        }} for key in ("openai", "anthropic", "deepseek", "moonshotai")})
    # 每次使用固定 Turn 设置选择替身目录身份。
    def provider(self, settings):
        return BrowserFixtureProvider(settings["provider"])

    # 避开真实网络目录探测；返回值仍通过正常模型能力校验。
    def connection(self, payload=None, *, force=False):
        settings = payload or self._use("settings")
        status = self.provider(settings).check()
        return {"ready": status.ready, "provider": status.provider_id, "details": status.details}


# 只绑定 loopback，与标准页面共用 Handler 和安全响应头。
def main():
    parser = argparse.ArgumentParser(description="Myth deterministic browser regression server")
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--model-delay", type=float, default=0.35)
    parser.add_argument("--standard", action="store_true", help="Use production providers for read-only startup checks")
    args = parser.parse_args()
    BrowserFixtureProvider.delay_seconds = args.model_delay
    service = AgentWebService(Path(args.root))
    # 标准空工作区只做页面读取；业务交互必须使用固定 Provider 的另一个根目录。
    if not args.standard:
        service.workspace = BrowserFixtureWorkspace(service.root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    print(f"UI regression fixture: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.workspace.stop_scheduler()
        server.server_close()


if __name__ == "__main__":
    main()
