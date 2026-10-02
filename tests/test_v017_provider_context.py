from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.acceptance import ContextBudgetError
from myth.conversation_context import conversation_budget_bytes
from myth.runtime import MythRuntime
from myth.workspace import Workspace


class ProviderContextBudgetTests(unittest.TestCase):
    def test_budget_is_derived_from_num_ctx_output_and_reserve(self):
        self.assertEqual(conversation_budget_bytes(4096,1024),5120)
        self.assertEqual(conversation_budget_bytes(8192,2048),11264)
        with self.assertRaises(ContextBudgetError):
            conversation_budget_bytes(2048,1800)

    def test_workspace_settings_persist_num_ctx_and_temperature(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            repo=Workspace(runtime).repository
            saved=repo.save_settings({
                "provider":"ollama",
                "model":"demo",
                "ollama_url":"http://127.0.0.1:11434",
                "max_steps":8,
                "max_output_tokens":1024,
                "num_ctx":4096,
                "temperature":0.3,
                "thinking":False,
            })
            self.assertEqual(saved["num_ctx"],4096)
            self.assertEqual(saved["temperature"],0.3)
            self.assertEqual(repo.settings()["num_ctx"],4096)

    def test_old_settings_are_upgraded_with_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            workspace=Workspace(runtime)
            with runtime.store.tx() as db:
                db.execute(
                    "INSERT INTO workspace_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json",
                    ('{"provider":"ollama","model":"old","ollama_url":"http://127.0.0.1:11434","max_steps":12,"max_output_tokens":2048,"thinking":false}',),
                )
            settings=workspace.repository.settings()
            self.assertEqual(settings["num_ctx"],8192)
            self.assertEqual(settings["temperature"],0.0)


if __name__=="__main__":
    unittest.main()
