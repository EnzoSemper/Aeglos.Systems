"""
AEGLOS Analytics Pro - Python SDK Client
"""

import json
from typing import Any

import requests


class AeglosClient:
    """Python SDK for the AEGLOS Analytics Pro API."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.session.headers["User-Agent"] = "AeglosClient/1.0"

    def _get(self, path: str, params: dict | None = None) -> Any:
        r = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Any) -> Any:
        r = self.session.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ── Core ──────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        return self._get("/health")

    def ingest(self, data_points: list[dict]) -> dict:
        return self._post("/ingest", {"data": data_points})

    def analyze(self, data_points: list[dict]) -> dict:
        return self._post("/analyze", {"data": data_points})

    def forecast(self, hours: int = 72) -> dict:
        return self._get("/forecast", {"hours": hours})

    def encrypt(self, plaintext: str, password: str) -> dict:
        return self._post("/encrypt", {"plaintext": plaintext, "password": password})

    def decrypt(self, payload: dict, password: str) -> dict:
        return self._post("/decrypt", {"payload": payload, "password": password})

    def metrics(self) -> dict:
        return self._get("/metrics")

    def benchmark(self, points: int = 100_000) -> dict:
        return self._get("/benchmark", {"points": points})

    # ── GeoThreat ─────────────────────────────────────────────────────────────

    def geothreat_ingest(self) -> dict:
        return self._post("/api/v1/geothreat/ingest", {})

    def geothreat_events(
        self,
        limit: int = 50,
        region: str = "",
        severity: str = "",
    ) -> dict:
        params = {"limit": limit}
        if region:
            params["region"] = region
        if severity:
            params["severity"] = severity
        return self._get("/api/v1/geothreat/events", params)

    def geothreat_statistics(self) -> dict:
        return self._get("/api/v1/geothreat/statistics")

    def geothreat_sources(self) -> dict:
        return self._get("/api/v1/geothreat/sources")

    def geothreat_regions(self) -> dict:
        return self._get("/api/v1/geothreat/regions")

    def geothreat_severity(self) -> dict:
        return self._get("/api/v1/geothreat/severity")


# ── CLI quick-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    client = AeglosClient()
    print("=== AEGLOS Analytics Pro - SDK Test ===")

    try:
        h = client.health()
        print(f"Health: {h['status']}  ML trained: {h['ml_trained']}")
    except Exception as exc:
        print(f"Health check failed: {exc}")
        sys.exit(1)

    try:
        stats = client.geothreat_statistics()
        print(f"GeoThreat events: {stats['total_events']}  sources online: {stats['sources_online']}")
    except Exception as exc:
        print(f"GeoThreat stats: {exc}")

    try:
        result = client.analyze([
            {"severity": "critical", "confidence": 0.95, "keywords_matched": ["war", "attack"]},
            {"severity": "low", "confidence": 0.40, "keywords_matched": []},
        ])
        print(f"Analysis: {result['total_points']} points, {result['anomalies_detected']} anomalies")
    except Exception as exc:
        print(f"Analysis failed: {exc}")

    print("SDK test complete.")
