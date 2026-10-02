from __future__ import annotations

from pathlib import Path
import unittest

from myth.web_workspace import ConversationWebService


class CacheObservabilityTests(unittest.TestCase):
    def test_cache_hit_summary_uses_provider_reported_cached_input_tokens(self):
        summary=ConversationWebService._model_usage_summary([
            {"usage":{"input_tokens":800,"output_tokens":100,"cached_input_tokens":500}},
            {"usage":{"input_tokens":200,"output_tokens":50,"cached_input_tokens":100}},
        ])
        self.assertEqual(summary["input_tokens"],1000)
        self.assertEqual(summary["cached_input_tokens"],600)
        self.assertAlmostEqual(summary["cache_hit_rate"],0.6)
        self.assertTrue(summary["cache_metrics_available"])

    def test_cache_hit_is_unknown_when_provider_does_not_report_it(self):
        summary=ConversationWebService._model_usage_summary([
            {"usage":{"input_tokens":800,"output_tokens":100}},
        ])
        self.assertEqual(summary["input_tokens"],800)
        self.assertIsNone(summary["cached_input_tokens"])
        self.assertIsNone(summary["cache_hit_rate"])
        self.assertFalse(summary["cache_metrics_available"])

    def test_runtime_observatory_keeps_cache_hit_visible(self):
        webui=Path(__file__).resolve().parents[1]/"src"/"myth"/"webui"
        inspector=(webui/"inspector.js").read_text(encoding="utf-8")
        self.assertIn('"Cache hit"',inspector)
        self.assertIn("cache_metrics_available",inspector)
        self.assertIn("provider not reported",inspector)


if __name__=="__main__":
    unittest.main()
