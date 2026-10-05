"""公开计价、数值边界和入口重试回归；固定目录不证明远端标价/推理质量。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.adapters.model_catalog import PublicModelCatalog
from myth.domain import IdentityConflict
from myth.domain import digest_json
from myth.model_capabilities import normalize_thinking
from myth.platform.model_pool import clean_pool
from myth.platform.model_pool import pricing_identity
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# 明确的价格与缺省占位用例，不把未知值零填成免费。
DATA = {"openai": {"models": {"demo": {"cost": {"input": 2, "output": 8}, "limit": {"output": 8192}},
                               "placeholder": {"cost": {"input": 0, "output": 0}}}}}


class ModelCatalogTests(unittest.TestCase):
    """固定公开目录的精确匹配、缓存边界和历史快照不变量。"""

    def test_exact_channel_zero_and_unknown(self):
        """同名不同渠道、零占位与订阅渠道不得沿用 API 单价。"""
        catalog = PublicModelCatalog(lambda: DATA)
        info = catalog.info("openai", "demo")
        self.assertEqual(info["pricing"]["input"], 2)
        self.assertEqual(info["max_output_tokens"], 8192)
        for provider, model in [("anthropic", "demo"), ("openai", "demo-dated"), ("openai", "placeholder"), ("chatgpt", "demo"), ("ollama", "demo")]:
            self.assertIsNone(catalog.info(provider, model)["pricing"])
        with self.assertRaises(ValueError):
            catalog.info("openai", "demo", force="yes")

    def test_stale_failure_retains_timestamp_and_throttles(self):
        """成功时间只在成功下载后前进；过期错误保留来源，并限制失败刷新频率。"""
        calls = []

        def loader():
            """第二次网络读取按故障窗口失败。"""
            calls.append(True)
            if len(calls) > 1:
                raise OSError("offline")
            return DATA

        catalog = PublicModelCatalog(loader)
        with patch("myth.adapters.model_catalog.time.monotonic", return_value=100):
            first = catalog.info("openai", "demo")
        with patch("myth.adapters.model_catalog.time.monotonic", return_value=3800):
            second = catalog.info("openai", "demo", force=True)
            catalog.info("openai", "demo", force=True)
        self.assertTrue(second["stale"])
        self.assertEqual(second["checked_at"], first["checked_at"])
        self.assertEqual(len(calls), 2)

    def test_quote_preserves_contract_and_checks_model_ceiling(self):
        """合同覆盖明确保留，公共目录能证明的输出上限仍不可绕过。"""
        catalog = PublicModelCatalog(lambda: DATA)
        settings = {"provider": "openai", "model": "demo", "max_output_tokens": 2048}
        quoted = catalog.quote_settings(settings)
        self.assertEqual(quoted["model_pool"]["main_pricing"]["source"], "models.dev")
        self.assertNotIn("model_pool", settings)
        manual = {"currency": "CNY", "input": 1, "output": 2}
        settings["model_pool"] = {"children": [], "main_pricing": manual}
        self.assertEqual(catalog.quote_settings(settings)["model_pool"]["main_pricing"], manual)
        with self.assertRaises(ValueError):
            catalog.quote_settings({**settings, "max_output_tokens": 100000})

    def test_unpriced_saved_identity_keeps_its_exact_shape(self):
        """公共价格只替换原有空价位置，未配置价格的历史身份无需迁移或重写。"""
        settings = {"model_pool": {"main_pricing": None, "children": [{"id": "a", "pricing": None}]}}
        self.assertEqual(digest_json(settings), digest_json(pricing_identity(settings)))
        priced = {"model_pool": {"main_pricing": {"source": "models.dev"}, "children": [{"id": "a", "pricing": {"source": "models.dev"}}]}}
        self.assertEqual(digest_json(settings), digest_json(pricing_identity(priced)))

    def test_admission_freezes_quote_without_breaking_retry(self):
        """同请求在目录刷新后仍返回原 Run 与价格；用户改消息或合同单价仍冲突。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            repo = Workspace(runtime).repository
            settings = repo.save_settings({"provider": "openai", "model": "demo"})
            catalog = PublicModelCatalog(lambda: DATA)
            first_settings = catalog.quote_settings(settings)
            sid = repo.create_session({"title": "计价快照"})["id"]
            first = repo.create_turn(sid, "hello", "same-request", _settings=first_settings)
            next_settings = catalog.quote_settings(settings)
            next_settings["model_pool"]["main_pricing"].update(input=999, checked_at="2026-10-06T00:00:00+00:00")
            again = repo.create_turn(sid, "hello", "same-request", _settings=next_settings)
            self.assertEqual(first["run_id"], again["run_id"])
            self.assertEqual(again["settings"]["model_pool"]["main_pricing"]["input"], 2)
            with self.assertRaises(IdentityConflict):
                repo.create_turn(sid, "changed", "same-request", _settings=next_settings)
            next_settings["model_pool"]["main_pricing"] = {"currency": "USD", "input": 2, "output": 8}
            with self.assertRaises(IdentityConflict):
                repo.create_turn(sid, "hello", "same-request", _settings=next_settings)

    def test_parameter_bounds_reject_number_thinking_and_boolean_temperature(self):
        """HTTP/仓储不信任浏览器上下限；数字 Thinking、超界与布尔温度均明确拒绝。"""
        for value in [100000, "100000", {}, [], float("nan")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_thinking(value)
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(Path(tmp)) as runtime:
            repo = Workspace(runtime).repository
            for field, value in [("temperature", True), ("temperature", 100000), ("temperature", float("nan")), ("max_steps", 100000), ("max_output_tokens", 1000000)]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    repo.save_settings({"provider": "openai", "model": "demo", field: value})
            with self.assertRaises(ValueError):
                repo.save_settings({"provider": "anthropic", "model": "demo", "temperature": 1.1})
            for field in ("max_steps", "temperature", "max_output_tokens", "num_ctx", "thinking"):
                with self.subTest(child=field), self.assertRaises(ValueError):
                    clean_pool({"children": [{"id": "child", "provider": "openai", "model": "demo", field: 1000000}]})
