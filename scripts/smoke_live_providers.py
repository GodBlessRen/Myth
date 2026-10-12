"""真实 Provider/OAuth 冒烟探针：仅用户显式启动，不读取/打印任何密钥。

执行: MYTH_LIVE_SMOKE=1 MYTH_ROOT=<已授权的本机 Myth 根目录> python scripts/smoke_live_providers.py
默认只观察真实供应商模型目录和 OAuth 脱敏状态；不尝试登录、刷新或创建计费 Run。
可选: MYTH_LIVE_MODEL=provider:model 启用单次真实生成（必须确认可能产生费用）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> int:
    """实测记录只保留类别和布尔事实；异常详情可能带密钥，禁止输出。"""
    if os.environ.get("MYTH_LIVE_SMOKE") != "1":
        print("SKIP: set MYTH_LIVE_SMOKE=1 to explicitly permit external provider checks")
        return 2
    from myth.web import AgentWebService
    from myth.models import ModelMessage, ModelRequest, STEP_DECISION_SCHEMA, parse_step_decision

    root = os.environ.get("MYTH_ROOT")
    if not root or not Path(root).is_dir():
        print("SKIP: MYTH_ROOT must name an existing local runtime directory")
        return 2
    service = AgentWebService(Path(root))
    report: dict = {"evidence": "live-provider-network", "providers": {}, "oauth": {}}
    for name in ("ollama", "openai", "deepseek", "anthropic", "kimi", "chatgpt", "claude_oauth"):
        try:
            status = service._provider({"provider": name}).check()
            details = status.details or {}
            report["providers"][name] = {
                "ready": status.ready,
                "auth_type": status.auth_type,
                "model_count": len(details["models"]) if isinstance(details.get("models"), list) else None,
            }
        except Exception:
            report["providers"][name] = {"ready": False, "probe_error": True}
    for name, getter in (("chatgpt", service.chatgpt_status), ("claude", service.claude_status)):
        try:
            raw = getter().get("status") or {}
            report["oauth"][name] = {
                "connected": raw.get("connected") is True,
                "login_revision_observed": bool(raw.get("login_revision")),
            }
        except Exception:
            report["oauth"][name] = {"connected": False, "probe_error": True}

    chosen = os.environ.get("MYTH_LIVE_MODEL", "").strip()
    failed = False
    if chosen:
        name, sep, model = chosen.partition(":")
        if not sep or name not in report["providers"] or not model:
            print("INVALID MYTH_LIVE_MODEL: use provider:model, no credentials")
            return 2
        try:
            provider = service._provider({"provider": name})
            response = provider.invoke(ModelRequest(model=model, messages=(
                ModelMessage(role="system", content="Reply with the required StepDecision JSON only."),
                ModelMessage(role="user", content="Answer the arithmetic question: what is 2+2?"),
            ), response_schema=STEP_DECISION_SCHEMA, max_output_tokens=512, thinking=None))
            decision = parse_step_decision(response.text)
            report["generation"] = {
                "provider": name, "schema_valid": True, "complete": decision.decision_type == "request_completion",
                "answer_mentions_four": "4" in (decision.claim or ""),
                "usage_reported": sorted(k for k in response.usage if k in {"input_tokens", "output_tokens"}),
            }
            failed = not (report["generation"]["complete"] and report["generation"]["answer_mentions_four"])
        except Exception:
            failed = True
            report["generation"] = {"provider": name, "schema_valid": False, "failed": True}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("NOTE: connectivity is not generation; OAuth status is not an account-level interactive login test.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
