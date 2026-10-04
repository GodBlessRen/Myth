"""固定本机开销对照，不访问真实模型或读取用户项目。
--source 指向待比较源码；相同合成 SQLite/Memory/目录延迟夹具验证索引、内存和重复 preflight。
"""

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch


# 中位数降低单次调度噪声；结果仅适用于脚本声明的固定数据量。
def median_ms(operation, repeats=9):
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        operation()
        values.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(values), 3)


# 临时独立 Runtime 由本函数拥有；源码选择发生在导入之前，避免混用两版实现。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from myth.runtime import MythRuntime
    from myth.workspace import Workspace
    from myth.models import ProviderStatus
    from myth.web_workspace import ConversationWebService
    from myth.platform.memory_store import SqliteMemoryStore

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with MythRuntime(root) as runtime:
            Workspace(runtime)
            db = runtime.store.db
            with runtime.store.tx():
                db.executemany("INSERT INTO workspace_sessions(id,title) VALUES (?,?)",
                    [(f"session-{i}", f"fixture {i}") for i in range(1000)])
                db.executemany("INSERT INTO workspace_messages(id,session_id,role,content,metadata_json) VALUES (?,?,?,?,?)",
                    [(f"message-{i}", f"session-{i % 1000}", "user", "synthetic body", "{}") for i in range(100000)])
            sql = "SELECT * FROM workspace_messages WHERE session_id=? ORDER BY rowid"
            query = lambda: db.execute(sql, ("session-42",)).fetchall()
            query()
            output = {"fixture": {"sessions": 1000, "messages": 100000, "memories": 10000,
                "preflight_calls": 10, "simulated_catalog_ms": 20}, "real_model": False,
                "message_query_ms": median_ms(query),
                "message_rows": len(query()),
                "message_query_plan": [row["detail"] for row in db.execute("EXPLAIN QUERY PLAN " + sql, ("session-42",))]}
            memory = SqliteMemoryStore(runtime)
            with runtime.store.tx():
                db.executemany("INSERT INTO workspace_memories(memory_id,kind,text,source_ref) VALUES (?,?,?,?)",
                    [(f"memory-{i:05}", "semantic", "apple banana " + "x" * 1000, f"source-{i}") for i in range(10000)])
            # 固定同一万条 Memory，预热一次后量测反复装配；反映普通 API 请求的仓储初始化开销。
            Workspace(runtime)
            output["workspace_reopen_ms"] = median_ms(lambda: Workspace(runtime), repeats=5)
            tracemalloc.start()
            start = time.perf_counter()
            found = memory.search_report("apple banana", limit=6)
            output["memory_ms"] = round((time.perf_counter() - start) * 1000, 3)
            output["memory_peak_bytes"] = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            output["memory_ids"] = [item["memory_id"] for item in found["memories"]]
            output["memory_retrieval"] = found["retrieval"]
        service = ConversationWebService(root)
        calls = []

        # 模拟目录网络往返；二十毫秒是夹具，不是 OpenAI/Ollama 实测时延。
        def catalog(_provider):
            calls.append(1)
            time.sleep(0.02)
            return ProviderStatus("ollama", True, details={"models": ["fixture"]})
        with patch("myth.web_workspace.OllamaProvider.check", catalog):
            start = time.perf_counter()
            for _ in range(10):
                service.connection({"provider": "ollama", "ollama_url": "http://127.0.0.1:11434"})
            output["preflight_total_ms"] = round((time.perf_counter() - start) * 1000, 3)
            output["catalog_requests"] = len(calls)
        print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
