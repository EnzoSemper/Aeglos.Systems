"""
AEGLOS Analytics Pro - High-Performance Data Ingestion Pipeline
Async batch processing with metrics tracking.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import numpy as np

from config import settings

logger = logging.getLogger("data_pipeline")


class PipelineMetrics:
    def __init__(self):
        self.total_processed: int = 0
        self.current_rate: float = 0.0
        self.peak_rate: float = 0.0
        self.avg_latency_ms: float = 0.0
        self._latency_window: deque[float] = deque(maxlen=1000)
        self._rate_window: deque[tuple[float, int]] = deque(maxlen=60)  # (ts, count)
        self._batch_count: int = 0
        self._error_count: int = 0
        self._start_time: float = time.monotonic()

    def record_batch(self, count: int, latency_ms: float):
        self.total_processed += count
        self._batch_count += 1
        self._latency_window.append(latency_ms)
        self.avg_latency_ms = float(np.mean(self._latency_window))

        now = time.monotonic()
        self._rate_window.append((now, count))
        # Compute rate over last 10 seconds
        cutoff = now - 10.0
        recent = [(ts, cnt) for ts, cnt in self._rate_window if ts >= cutoff]
        if len(recent) >= 2:
            elapsed = recent[-1][0] - recent[0][0]
            if elapsed > 0:
                total = sum(c for _, c in recent)
                self.current_rate = total / elapsed
                if self.current_rate > self.peak_rate:
                    self.peak_rate = self.current_rate

    def record_error(self):
        self._error_count += 1

    def to_dict(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time
        return {
            "total_processed": self.total_processed,
            "current_rate": round(self.current_rate, 1),
            "peak_rate": round(self.peak_rate, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "batch_count": self._batch_count,
            "error_count": self._error_count,
            "uptime_seconds": round(uptime, 1),
            "throughput_target": settings.MAX_DATA_POINTS_PER_SEC,
        }


class DataPipeline:
    """Async batch processing pipeline."""

    def __init__(self):
        self.metrics = PipelineMetrics()
        self._buffer: deque[dict] = deque(maxlen=settings.BUFFER_SIZE)
        self._processing_lock = asyncio.Lock()

    async def ingest_batch(self, data_points: list[dict]) -> dict[str, Any]:
        """Ingest a batch of data points, returning processing metrics."""
        if not data_points:
            return {"status": "ok", "processed": 0}

        t0 = time.perf_counter()
        async with self._processing_lock:
            processed = 0
            errors = 0
            results = []

            # Process in chunks
            for i in range(0, len(data_points), settings.BATCH_SIZE):
                chunk = data_points[i:i + settings.BATCH_SIZE]
                chunk_t0 = time.perf_counter()

                for dp in chunk:
                    try:
                        normalized = self._normalize(dp)
                        self._buffer.append(normalized)
                        processed += 1
                    except Exception as exc:
                        errors += 1
                        logger.debug("Point normalization error: %s", exc)

                chunk_latency = (time.perf_counter() - chunk_t0) * 1000
                self.metrics.record_batch(len(chunk), chunk_latency)
                results.append({
                    "chunk": i // settings.BATCH_SIZE,
                    "size": len(chunk),
                    "latency_ms": round(chunk_latency, 2),
                })
                if errors:
                    self.metrics.record_error()

        total_latency = (time.perf_counter() - t0) * 1000
        return {
            "status": "ok",
            "processed": processed,
            "errors": errors,
            "total_latency_ms": round(total_latency, 2),
            "chunks": results,
            "buffer_size": len(self._buffer),
        }

    async def benchmark(self, num_points: int = 100_000) -> dict[str, Any]:
        """Run a throughput benchmark."""
        rng = np.random.default_rng(42)
        data = [
            {
                "value": float(rng.random()),
                "timestamp": time.time(),
                "source": "benchmark",
                "severity": "low",
                "confidence": float(rng.random()),
            }
            for _ in range(num_points)
        ]

        t0 = time.perf_counter()
        result = await self.ingest_batch(data)
        elapsed = time.perf_counter() - t0
        throughput = num_points / elapsed if elapsed > 0 else 0

        return {
            "benchmark_points": num_points,
            "elapsed_sec": round(elapsed, 3),
            "throughput_per_sec": round(throughput, 0),
            "target_per_sec": settings.MAX_DATA_POINTS_PER_SEC,
            "avg_latency_ms": round(result["total_latency_ms"] / max(num_points // settings.BATCH_SIZE, 1), 2),
            "latency_target_ms": settings.LATENCY_TARGET_MS,
            "target_met": result["total_latency_ms"] / max(num_points // settings.BATCH_SIZE, 1) <= settings.LATENCY_TARGET_MS,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_metrics(self) -> dict[str, Any]:
        return self.metrics.to_dict()

    def get_buffer_sample(self, n: int = 10) -> list[dict]:
        items = list(self._buffer)
        return items[-n:]

    @staticmethod
    def _normalize(dp: dict) -> dict:
        """Validate and normalize a data point."""
        return {
            "value": float(dp.get("value", 0.0)),
            "timestamp": dp.get("timestamp", time.time()),
            "source": str(dp.get("source", "unknown"))[:64],
            "severity": dp.get("severity", "low"),
            "confidence": min(max(float(dp.get("confidence", 0.5)), 0.0), 1.0),
            "region": dp.get("region", "Global"),
            "metadata": dp.get("metadata", {}),
        }


# Module-level singleton
pipeline = DataPipeline()
