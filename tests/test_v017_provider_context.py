"""回归边界：窗口、温度与旧设置升级。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.acceptance import ContextBudgetError
from myth.conversation_context import conversation_budget_bytes
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# 窗口、温度与旧设置升级的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ProviderContextBudgetTests(unittest.TestCase):
    # 回归断言：Ollama 窗口、输出和协议预留共同决定保守字节预算。
    def test_budget_is_derived_from_num_ctx_output_and_reserve(self):
        self.assertEqual(conversation_budget_bytes(4096, 1024), 5120)
        self.assertEqual(conversation_budget_bytes(8192, 2048), 11264)
        with self.assertRaises(ContextBudgetError):
            conversation_budget_bytes(2048, 1800)

    # 回归断言：窗口/温度设置持久化并固定新 Turn 请求。
    def test_workspace_settings_persist_num_ctx_and_temperature(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            repo = Workspace(runtime).repository
            saved = repo.save_settings(
                {
                    "provider": "ollama",
                    "model": "demo",
                    "ollama_url": "http://127.0.0.1:11434",
                    "max_steps": 8,
                    "max_output_tokens": 1024,
                    "num_ctx": 4096,
                    "temperature": 0.3,
                    "thinking": False,
                }
            )
            self.assertEqual(saved["num_ctx"], 4096)
            self.assertEqual(saved["temperature"], 0.3)
            self.assertEqual(repo.settings()["num_ctx"], 4096)



if __name__ == "__main__":
    unittest.main()
