"""
AEGLOS Analytics Pro - Test Suite
"""

import asyncio
import sys
import time
import unittest


class TestEncryption(unittest.TestCase):
    def setUp(self):
        from encryption import decrypt, encrypt
        self.encrypt = encrypt
        self.decrypt = decrypt

    def test_roundtrip(self):
        plaintext = "TOP SECRET//SCI - NOFORN - AEGLOS test payload"
        password = "test-password-secure-1234"
        payload = self.encrypt(plaintext, password)
        result = self.decrypt(payload, password)
        self.assertEqual(result, plaintext)

    def test_wrong_password(self):
        from cryptography.exceptions import InvalidTag
        payload = self.encrypt("secret", "correct-password")
        with self.assertRaises(Exception):
            self.decrypt(payload, "wrong-password")

    def test_payload_fields(self):
        payload = self.encrypt("hello", "pass12345")
        self.assertIn("algorithm", payload)
        self.assertIn("salt", payload)
        self.assertIn("nonce", payload)
        self.assertIn("ciphertext", payload)
        self.assertEqual(payload["algorithm"], "AES-256-GCM")

    def test_unique_nonces(self):
        p1 = self.encrypt("data", "pass12345")
        p2 = self.encrypt("data", "pass12345")
        self.assertNotEqual(p1["nonce"], p2["nonce"])
        self.assertNotEqual(p1["salt"], p2["salt"])

    def test_token_generation(self):
        from encryption import generate_token
        t1 = generate_token()
        t2 = generate_token()
        self.assertNotEqual(t1, t2)
        self.assertGreater(len(t1), 20)


class TestMLEngine(unittest.TestCase):
    def setUp(self):
        from ml_engine import MLEngine
        self.engine = MLEngine()
        self.engine.train(n_samples=500)  # fast training for tests

    def test_training(self):
        info = self.engine.get_model_info()
        self.assertTrue(info["trained"])
        self.assertGreater(info["accuracy"], 0.5)

    def test_analyze_returns_results(self):
        data = [
            {"severity": "critical", "confidence": 0.95, "keywords_matched": ["war"]},
            {"severity": "low", "confidence": 0.3, "keywords_matched": []},
            {"severity": "high", "confidence": 0.78, "keywords_matched": ["military", "tension"]},
        ]
        result = self.engine.analyze(data)
        self.assertEqual(result["total_points"], 3)
        self.assertIn("anomalies_detected", result)
        self.assertEqual(len(result["results"]), 3)

    def test_forecast_structure(self):
        fc = self.engine.forecast(horizon_hours=24)
        self.assertEqual(fc["horizon_hours"], 24)
        self.assertIn("forecast", fc)
        self.assertGreater(len(fc["forecast"]), 0)
        point = fc["forecast"][0]
        self.assertIn("hour", point)
        self.assertIn("threat_level", point)
        self.assertIn("confidence", point)

    def test_empty_analyze(self):
        result = self.engine.analyze([])
        self.assertIn("error", result)


class TestDataPipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from data_pipeline import DataPipeline
        self.pipeline = DataPipeline()

    async def test_ingest_batch(self):
        data = [{"value": i * 0.01, "source": "test", "severity": "low"} for i in range(100)]
        result = await self.pipeline.ingest_batch(data)
        self.assertEqual(result["processed"], 100)
        self.assertEqual(result["errors"], 0)

    async def test_empty_batch(self):
        result = await self.pipeline.ingest_batch([])
        self.assertEqual(result["processed"], 0)

    async def test_benchmark(self):
        result = await self.pipeline.benchmark(num_points=1000)
        self.assertIn("throughput_per_sec", result)
        self.assertGreater(result["throughput_per_sec"], 0)

    def test_metrics(self):
        metrics = self.pipeline.get_metrics()
        self.assertIn("total_processed", metrics)
        self.assertIn("avg_latency_ms", metrics)


class TestGeoThreatPipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            from geothreat_pipeline import GeoThreatPipeline
            self.pipeline = GeoThreatPipeline()
            self.available = True
        except ImportError:
            self.available = False

    def test_available(self):
        if not self.available:
            self.skipTest("feedparser/aiohttp not installed")

    def test_get_statistics_empty(self):
        if not self.available:
            self.skipTest("feedparser/aiohttp not installed")
        stats = self.pipeline.get_statistics()
        self.assertIn("total_events", stats)
        self.assertIn("sources_total", stats)
        self.assertEqual(stats["sources_total"], 9)

    def test_get_recent_events_empty(self):
        if not self.available:
            self.skipTest("feedparser/aiohttp not installed")
        events = self.pipeline.get_recent_events()
        self.assertIsInstance(events, list)

    def test_region_classification(self):
        if not self.available:
            self.skipTest("feedparser/aiohttp not installed")
        from geothreat_pipeline import _classify_region
        region, kw = _classify_region("Iran launched missiles at Iraq near Baghdad")
        self.assertEqual(region, "Middle East")
        self.assertTrue(len(kw) > 0)

    def test_severity_classification(self):
        if not self.available:
            self.skipTest("feedparser/aiohttp not installed")
        from geothreat_pipeline import _classify_severity
        sev, conf = _classify_severity("bombing attack killed many casualties")
        self.assertEqual(sev, "critical")
        self.assertGreater(conf, 0.6)

        sev2, _ = _classify_severity("two countries held diplomatic talks")
        self.assertIn(sev2, ("low", "moderate"))


class TestConfig(unittest.TestCase):
    def test_settings_loaded(self):
        from config import settings
        self.assertEqual(settings.APP_NAME, "AEGLOS Analytics Pro")
        self.assertEqual(settings.VERSION, "1.0.0")
        self.assertEqual(len(settings.RSS_SOURCES), 9)
        self.assertIn("Middle East", settings.REGION_KEYWORDS)
        self.assertIn("critical", settings.SEVERITY_KEYWORDS)


def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestEncryption))
    suite.addTests(loader.loadTestsFromTestCase(TestMLEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestDataPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestGeoThreatPipeline))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
