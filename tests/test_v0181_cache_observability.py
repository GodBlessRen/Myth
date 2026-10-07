"""回归边界：实际缓存计量与缺测显示。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import unittest

from myth.web_workspace import ConversationWebService


# 实际缓存计量与缺测显示的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class CacheObservabilityTests(unittest.TestCase):
    # 回归断言：缓存比率只用供应商实际报告的 cached input tokens。
    def test_cache_hit_summary_uses_provider_reported_cached_input_tokens(self):
        summary = ConversationWebService._model_usage_summary(
            [
                {
                    "usage": {
                        "input_tokens": 800,
                        "output_tokens": 100,
                        "cached_input_tokens": 500,
                    }
                },
                {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 50,
                        "cached_input_tokens": 100,
                    }
                },
            ]
        )
        self.assertEqual(summary["input_tokens"], 1000)
        self.assertEqual(summary["cached_input_tokens"], 600)
        self.assertAlmostEqual(summary["cache_hit_rate"], 0.6)
        self.assertTrue(summary["cache_metrics_available"])

    # 回归断言：缺缓存字段显示 N/A，不能造零命中或全命中。
    def test_cache_hit_is_unknown_when_provider_does_not_report_it(self):
        summary = ConversationWebService._model_usage_summary(
            [
                {"usage": {"input_tokens": 800, "output_tokens": 100}},
            ]
        )
        self.assertEqual(summary["input_tokens"], 800)
        self.assertIsNone(summary["cached_input_tokens"])
        self.assertIsNone(summary["cache_hit_rate"])
        self.assertFalse(summary["cache_metrics_available"])

    # 回归断言：模型 wall-clock 仅聚合 Runtime 实测 provider_wall_ms，未报告时保持 N/A。
    def test_model_wall_summary_uses_runtime_measured_provider_time(self):
        summary = ConversationWebService._model_usage_summary(
            [
                {"usage": {"provider_wall_ms": 1250}},
                {"usage": {"provider_wall_ms": 2750}},
            ]
        )
        self.assertEqual(summary["provider_wall_ms"], 4000)
        self.assertTrue(summary["provider_wall_available"])

    # 回归断言：第三栏同时暴露总回复 Worked-time 与模型 provider wall，避免把两种耗时混成一个指标。
    def test_runtime_observatory_keeps_model_wall_visible(self):
        webui = Path(__file__).resolve().parents[1] / "src" / "myth" / "webui"
        inspector = (webui / "inspector.js").read_text(encoding="utf-8")
        self.assertIn('"Model wall"', inspector)
        self.assertIn("modelUsage.provider_wall_ms", inspector)
        self.assertIn("samples.provider_wall_ms", inspector)

    # 回归断言：第三栏缓存事实入口存在，缺测状态也可见。
    def test_runtime_observatory_keeps_cache_hit_visible(self):
        webui = Path(__file__).resolve().parents[1] / "src" / "myth" / "webui"
        inspector = (webui / "inspector.js").read_text(encoding="utf-8")
        self.assertIn('"Cache hit"', inspector)
        self.assertIn("cache_metrics_available", inspector)
        self.assertIn("provider not reported", inspector)


if __name__ == "__main__":
    unittest.main()
