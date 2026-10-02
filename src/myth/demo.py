"""入口演示夹具：每次生成独立源文件，演示不会覆盖用户数据。"""
import uuid
from .agent_runtime import AgentRuntime
from .providers.scripted import ScriptedPatchProvider


def create_demo(runtime):
    directory = runtime.runtime_dir / "demo-inputs"
    directory.mkdir(exist_ok=True)
    source = directory / f"welcome-{uuid.uuid4().hex[:8]}.txt"
    source.write_bytes("你好，Myth。\r\n把 foo 改成 bar，保留其他内容。\r\n".encode("utf-8"))
    provider = ScriptedPatchProvider()
    run_id = AgentRuntime(runtime).create_run(
        goal="将示例文件中的 foo 精确替换为 bar，并保留其他内容。", provider=provider,
        model="exact-patch-demo", allowed_files=(source,), max_steps=6,
        acceptance=[{"path": str(source), "old_text": "foo", "new_text": "bar", "expected_count": 1}])
    return run_id, provider
