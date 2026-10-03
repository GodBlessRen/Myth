"""长任务 Durable Executor 浸泡/故障注入工具。
默认用本地确定性 Provider 驱动一个单一 Conversation Run，持续多个模型/工具步骤；
可把总时长拉到 2–3 小时验证 heartbeat、checkpoint、context 与 no-replay，不访问真实模型。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import threading
import time

from myth.durable_executor import DurableExecutor, executor_snapshot
from myth.models import ModelResult, ProviderStatus
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# SoakProvider：只生成确定性 math.calculate 步骤；sleep 模拟长模型调用，不具有真实模型质量含义。
class SoakProvider:
    # 保存计划步骤、每次调用延迟与可选故障序号；调用计数只用于本次进程的测试夹具。
    def __init__(self, tool_steps: int, delay_seconds: float, fault_call: int = 0):
        # tool_steps：完成回复前应产生的工具步骤数量。
        self.tool_steps = int(tool_steps)
        # delay_seconds：每个模拟模型调用的墙钟等待秒数，用于撑开 lease/heartbeat 窗口。
        self.delay_seconds = max(0.0, float(delay_seconds))
        # fault_call：从 1 开始的可选不明确失败调用；0 表示不注入。
        self.fault_call = int(fault_call)
        # calls：已进入 invoke 的次数；报告用，不作为 Runtime 恢复事实。
        self.calls = 0
        # lock：保护 calls，使主监测线程读取时不与 invoke 竞争。
        self.lock = threading.Lock()
        # provider_id：与固定 Turn 设置一致；该替身不会访问 Ollama 网络。
        self.provider_id = "ollama"

    # 返回固定可用状态；只服务浸泡夹具，不证明真实 Ollama 已连接。
    def check(self):
        return ProviderStatus(
            self.provider_id,
            True,
            auth_type="soak-fixture",
            details={"models": ["soak-fixture"]},
        )

    # 模拟一次耗时模型调用；前 N 次提出无副作用计算工具，最后一次回复，可选某次抛出不明超时。
    def invoke(self, request):
        with self.lock:
            self.calls += 1
            call_no = self.calls
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fault_call and call_no == self.fault_call:
            raise RuntimeError("injected ambiguous provider timeout after Ticket")
        if call_no <= self.tool_steps:
            payload = {
                "action": "math.calculate",
                "reason": f"soak checkpoint {call_no}",
                "arguments": {"expression": f"{call_no}+1"},
            }
        else:
            payload = {
                "action": "reply",
                "reason": "all soak checkpoints completed",
                "claim": (
                    f"Durable soak completed {self.tool_steps} tool checkpoints "
                    f"across {call_no} model calls."
                ),
            }
        return ModelResult(
            json.dumps(payload, ensure_ascii=False),
            {
                "model_calls": 1,
                "input_tokens": 32,
                "output_tokens": 16,
            },
            {"fixture": "long-run-soak", "call": call_no},
        )

    # 线程安全读取当前调用次数；仅用于测试报告。
    def call_count(self) -> int:
        with self.lock:
            return int(self.calls)


# 构造 CLI 参数；默认 180 分钟对应真实长跑，CI/开发可显式传更短时长。
def build_parser():
    parser = argparse.ArgumentParser(
        description="Run one durable Conversation soak with optional UNKNOWN injection."
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--duration-minutes", type=float, default=180.0)
    parser.add_argument("--tool-steps", type=int, default=24)
    parser.add_argument(
        "--fault-call",
        type=int,
        default=0,
        help="1-based model call that raises an ambiguous post-Ticket timeout",
    )
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument("--keep", action="store_true")
    return parser


# 从当前 Run 读取可比较报告；所有预算/游标来自持久仓储而非 Provider 自述。
def snapshot(root: Path, run_id: str, provider: SoakProvider) -> dict:
    with MythRuntime(root) as runtime:
        workspace = Workspace(runtime)
        turn = workspace.repository.turn(run_id)
        meters = {item["meter"]: item for item in turn["budgets"]}
        return {
            "run_id": run_id,
            "status": turn["status"],
            "current_step": turn["current_step"],
            "cursor": turn["execution_cursor"],
            "provider_calls_observed": provider.call_count(),
            "model_calls_settled": int(meters["model_calls"]["settled"]),
            "model_calls_unknown": int(meters["model_calls"]["unknown_held"]),
            "tool_calls_settled": int(meters["tool_calls"]["settled"]),
            "events": len(workspace.repository.events(run_id)),
            "executor": executor_snapshot(runtime),
        }


# 执行一个单 Run 浸泡：主线程持续 tick 维持 Executor 租约，工作线程按正常 Driver/Receipt 路径推进。
def run_soak(
    root: Path,
    *,
    duration_minutes: float,
    tool_steps: int,
    fault_call: int = 0,
    poll_seconds: float = 0.25,
) -> dict:
    if not 1 <= int(tool_steps) <= 30:
        raise ValueError("tool_steps must be 1-30 so the final reply fits max_steps<=32")
    if duration_minutes < 0:
        raise ValueError("duration_minutes must be non-negative")
    total_calls = int(tool_steps) + 1
    delay_seconds = float(duration_minutes) * 60.0 / total_calls
    provider = SoakProvider(tool_steps, delay_seconds, fault_call)

    with MythRuntime(root) as runtime:
        workspace = Workspace(runtime)
        workspace.repository.save_settings(
            {
                "provider": "ollama",
                "model": "soak-fixture",
                "max_steps": total_calls,
                "max_output_tokens": 256,
                "num_ctx": 8192,
                "temperature": 0.0,
                "thinking": False,
            }
        )
        session_id = workspace.repository.create_session("Long-run soak")["id"]
        run_id = workspace.repository.create_turn(
            session_id,
            (
                f"Execute one durable soak with {tool_steps} checkpoints over "
                f"{duration_minutes} minutes."
            ),
            "long-run-soak",
        )["run_id"]

    executor = DurableExecutor(
        root,
        poll_seconds=max(0.05, poll_seconds),
        provider_factory=lambda settings: provider,
    )
    if not executor.claim():
        raise RuntimeError("another durable executor already owns this Runtime")

    started = time.monotonic()
    try:
        deadline = started + max(30.0, float(duration_minutes) * 60.0 + 60.0)
        while time.monotonic() < deadline:
            executor.tick()
            report = snapshot(root, run_id, provider)
            if report["status"] not in {"RUNNING", "INTERRUPTED"}:
                break
            time.sleep(max(0.05, poll_seconds))
        else:
            raise TimeoutError("soak exceeded its bounded deadline")
        executor.wait_for_idle(10.0)

        report = snapshot(root, run_id, provider)
        report["requested_duration_seconds"] = round(
            float(duration_minutes) * 60.0, 3
        )
        report["wall_elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["fault_call"] = int(fault_call)
        report["tool_steps_requested"] = int(tool_steps)

        if fault_call:
            before = provider.call_count()
            for _ in range(3):
                executor.tick()
                time.sleep(0.05)
            after = provider.call_count()
            report["no_replay_after_unknown"] = before == after
            if report["status"] != "UNKNOWN" or not report["no_replay_after_unknown"]:
                raise AssertionError(
                    "fault soak must stop UNKNOWN and never automatically replay"
                )
        else:
            if report["status"] != "COMPLETED":
                raise AssertionError(
                    f"healthy soak must complete, got {report['status']}"
                )
            if report["tool_calls_settled"] != int(tool_steps):
                raise AssertionError("not all deterministic tool checkpoints settled")
            if report["model_calls_settled"] != total_calls:
                raise AssertionError("model call count differs from planned soak")
        return report
    finally:
        executor.wait_for_idle(10.0)
        executor.release()


# CLI 入口管理临时目录；显式 root/--keep 时保留证据，默认退出后清理测试状态。
def main() -> int:
    args = build_parser().parse_args()
    temp = None
    if args.root is None:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
    else:
        root = args.root.resolve()
        root.mkdir(parents=True, exist_ok=True)

    try:
        report = run_soak(
            root,
            duration_minutes=args.duration_minutes,
            tool_steps=args.tool_steps,
            fault_call=args.fault_call,
            poll_seconds=args.poll_seconds,
        )
        report["root"] = str(root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.keep and temp is not None:
            temp.cleanup = lambda: None
        return 0
    finally:
        if temp is not None and not args.keep:
            temp.cleanup()


# 命令行直接执行时返回明确退出码，便于手动 2–3 小时浸泡或 CI quick smoke。
if __name__ == "__main__":
    raise SystemExit(main())
