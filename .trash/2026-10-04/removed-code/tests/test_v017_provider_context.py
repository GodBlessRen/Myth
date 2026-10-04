    # 回归断言：旧设置缺字段时补安全默认，不清库或放开预算。
    def test_old_settings_are_upgraded_with_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            workspace = Workspace(runtime)
            with runtime.store.tx() as db:
                db.execute(
                    "INSERT INTO workspace_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json",
                    (
                        '{"provider":"ollama","model":"old","ollama_url":"http://127.0.0.1:11434","max_steps":12,"max_output_tokens":2048,"thinking":false}',
                    ),
                )
            settings = workspace.repository.settings()
            self.assertEqual(settings["num_ctx"], 8192)
            self.assertEqual(settings["temperature"], 0.0)
