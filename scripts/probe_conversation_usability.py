"""量测固定中文输入的提示字节与公共前缀；不请求真实模型，不把字节称作 token。

在修改前后分别保存 JSON，输入、工具结果和窗口保持一致，便于独立复查减法效果。
"""

import argparse
import json
from pathlib import Path
import sys
import statistics
import tempfile
import time


def history_probe(count):
    """相同合成历史比较上下文准入的 SQL 次数和本机时间，不触发网络或真实 Token 计量。"""
    from myth.models import ModelResult
    from myth.runtime import MythRuntime
    from myth.workspace import Workspace

    class Provider:
        """固定短回答仅用于建立持久历史；不代表远端模型的生成或成本。"""
        provider_id = "ollama"

        def invoke(self, request):
            """返回完全确定的决定；不读取输入外的任何用户文件。"""
            text = json.dumps({"action": "reply", "reason": "fixture", "claim": "合成历史回答。" * 60}, ensure_ascii=False)
            return ModelResult(text, {"model_calls": 1, "input_tokens": 20, "output_tokens": 30}, {"text": text})

    with tempfile.TemporaryDirectory() as directory:
        with MythRuntime(Path(directory)) as runtime:
            workspace = Workspace(runtime)
            repo = workspace.repository
            repo.save_settings({"provider": "ollama", "model": "fixture"})
            sid = repo.create_session()["id"]
            for index in range(count):
                turn = repo.create_turn(sid, f"合成问题第 {index} 轮", f"seed-{index}")
                workspace.run(turn["run_id"], Provider())
            queries = []
            runtime.store.db.set_trace_callback(queries.append)
            repo.prepare_turn(sid, "继续这个会话", "probe")
            runtime.store.db.set_trace_callback(None)
            values = []
            for _ in range(3):
                started = time.perf_counter()
                repo.prepare_turn(sid, "继续这个会话", "probe")
                values.append((time.perf_counter() - started) * 1000)
            return {"historical_turns": count, "admission_sql_queries": len(queries),
                "historical_step_queries": sum("FROM workspace_steps WHERE run_id=" in query for query in queries),
                "prepare_median_ms": round(statistics.median(values), 3), "repeats": 3}


def main():
    """选择源码后才导入，确保基线和修复版本不会混入同一进程模块缓存。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
    parser.add_argument("--history-turns", type=int, default=0)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from myth.conversation import conversation_request

    settings = {"provider": "ollama", "model": "fixture", "num_ctx": 8192,
                "max_output_tokens": 2048, "max_steps": 12}
    rows = []
    for text in ("你好", "Python 的列表和元组有啥区别？", "帮我写一封请假信", "读取 README.md 并总结"):
        snapshot = {"project": {}, "knowledge": [], "memory": [], "turn_message_start": 0}
        messages = [{"role": "user", "content": text}]
        first = conversation_request(settings, snapshot, messages, [])
        second = conversation_request(settings, snapshot, messages, [{
            "step": 1, "state": "DONE", "capability": "project.read", "decision_id": "dec_fixture",
            "result": {"path": "README.md", "content": "固定资料正文", "next_offset": None},
        }], {"steering_note": "继续完成", "revision": 2})
        before = json.dumps([{"role": m.role, "content": m.content} for m in first.messages], ensure_ascii=False).encode()
        after = json.dumps([{"role": m.role, "content": m.content} for m in second.messages], ensure_ascii=False).encode()
        common = 0
        for left, right in zip(before, after):
            if left != right:
                break
            common += 1
        rows.append({"input": text, "message_bytes": len(before),
            "instruction_bytes": len(first.messages[0].content.encode()),
            "visible_tools": len(first.context_report["visible_tools"]),
            "shared_prefix_bytes_after_steer": common,
            "serialized_request_bytes": len(json.dumps(first.serializable(), ensure_ascii=False).encode())})
    result = {"boundary": "fixed synthetic inputs, no provider inference; bytes are not tokens", "samples": rows}
    if args.history_turns:
        result["history"] = history_probe(args.history_turns)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
