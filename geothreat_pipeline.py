"""
AEGLOS Analytics Pro - GeoThreat OSINT Pipeline
Real-time HUMINT/OSINT/GEOINT data ingestion from open sources.
"""

import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import aiohttp
import feedparser

from config import settings

logger = logging.getLogger("geothreat")

# BlueSky collector (optional — graceful if import fails)
try:
    from bluesky_source import collector as _bsky_collector
    BLUESKY_AVAILABLE = True
except ImportError:
    _bsky_collector = None  # type: ignore
    BLUESKY_AVAILABLE = False

# Prophet engine (optional — graceful if numpy/scipy not available)
try:
    from prophet_engine import compute_forecast, compute_patterns, compute_correlation_matrix
    PROPHET_AVAILABLE = True
except ImportError:
    compute_forecast = compute_patterns = compute_correlation_matrix = None  # type: ignore
    PROPHET_AVAILABLE = False

# Story clustering + translation engine
try:
    from dedup_translate import cluster_events as _cluster_events
    DEDUP_AVAILABLE = True
except ImportError:
    _cluster_events = None  # type: ignore
    DEDUP_AVAILABLE = False


class GeoThreatEvent:
    __slots__ = (
        "event_id", "timestamp", "source", "source_category",
        "title", "description", "url", "region", "severity",
        "keywords_matched", "confidence",
    )

    def __init__(
        self,
        source: str,
        source_category: str,
        title: str,
        description: str,
        url: str,
        region: str,
        severity: str,
        keywords_matched: list[str],
        confidence: float,
        timestamp: Optional[str] = None,
    ):
        content = f"{source}{title}{url}".encode()
        self.event_id = hashlib.sha1(content).hexdigest()[:16]
        # Use provided timestamp (article pubDate) if available, else ingest time
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.source = source
        self.source_category = source_category
        self.title = title
        self.description = description[:500] if description else ""
        self.url = url
        self.region = region
        self.severity = severity
        self.keywords_matched = keywords_matched
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "source_category": self.source_category,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "region": self.region,
            "severity": self.severity,
            "keywords_matched": self.keywords_matched,
            "confidence": self.confidence,
        }


class SourceStatus:
    def __init__(self, name: str, url: str, category: str, reliability: float):
        self.name = name
        self.url = url
        self.category = category
        self.reliability = reliability
        self.status = "unknown"
        self.last_checked: str = ""
        self.last_success: str = ""
        self.events_collected: int = 0
        self.error_count: int = 0
        self.latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "category": self.category,
            "reliability": self.reliability,
            "status": self.status,
            "last_checked": self.last_checked,
            "last_success": self.last_success,
            "events_collected": self.events_collected,
            "error_count": self.error_count,
            "latency_ms": round(self.latency_ms, 1),
        }


import re as _re


def _kw_match(keyword: str, lower_text: str) -> bool:
    """
    Match keyword against text.
    - Multi-word phrases: simple substring (e.g. "south china sea")
    - Short single words (≤4 chars, e.g. "pla", "drc", "uae"): whole-word only
      to prevent false positives like "pla" inside "implantation"
    - Longer single words: simple substring (fast, few false positives)
    """
    if " " in keyword:
        return keyword in lower_text
    if len(keyword) <= 4:
        return bool(_re.search(r"\b" + _re.escape(keyword) + r"\b", lower_text))
    return keyword in lower_text


def _classify_region(
    text: str,
    region_hint: Optional[str] = None,
) -> tuple[str, list[str]]:
    """
    Return (region_name, matched_keywords) from text.
    If no keyword matches and region_hint is provided, use the hint
    instead of falling back to 'Global'.
    """
    lower = text.lower()
    best_region = "Global"
    best_count = 0
    best_keywords: list[str] = []

    for region, keywords in settings.REGION_KEYWORDS.items():
        if not keywords:
            continue
        matched = [kw for kw in keywords if _kw_match(kw, lower)]
        if len(matched) > best_count:
            best_count = len(matched)
            best_region = region
            best_keywords = matched

    # If nothing matched and source has a regional focus, use that instead
    if best_count == 0 and region_hint:
        return region_hint, []

    return best_region, best_keywords


def _classify_severity(text: str) -> tuple[str, float]:
    """Return (severity_label, raw_confidence 0-1) from text.
    Raw confidence is keyword-match strength only; source band applied separately.
    """
    lower = text.lower()

    for severity in ("critical", "high", "moderate", "low"):
        keywords = settings.SEVERITY_KEYWORDS.get(severity, [])
        if not keywords:
            return "low", 0.50
        matched = [kw for kw in keywords if _kw_match(kw, lower)]
        if matched:
            # 0.50 base + 0.08 per keyword hit, capped at 0.99
            conf = min(0.50 + 0.08 * len(matched), 0.99)
            return severity, conf

    return "low", 0.50


# Confidence bands by source category
# LOW  (<0.40): social media / BlueSky posts
# MED  (0.41–0.68): news reports
# HIGH (0.69+): government / official sources
_CONF_BANDS: dict[str, tuple[float, float]] = {
    "government": (0.72, 0.97),
    "news":       (0.42, 0.68),
    "analysis":   (0.42, 0.65),
    "osint":      (0.22, 0.40),   # BlueSky OSINT accounts
    "search":     (0.10, 0.35),   # BlueSky keyword search results
}


def _apply_confidence_band(raw_conf: float, category: str) -> float:
    """Scale keyword-match confidence into the source-type band."""
    lo, hi = _CONF_BANDS.get(category, (0.30, 0.60))
    return round(lo + raw_conf * (hi - lo), 4)


def _parse_feed_entries(
    feed: feedparser.FeedParserDict,
    source_cfg: dict,
) -> list[GeoThreatEvent]:
    events: list[GeoThreatEvent] = []
    for entry in feed.entries[:30]:
        title = getattr(entry, "title", "")
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        url = getattr(entry, "link", "")
        combined = f"{title} {summary}"

        # Use article publication time if available — critical for time-series analysis
        pub_ts: str | None = None
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                try:
                    pub_ts = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
                    break
                except Exception:
                    pass

        # Translate non-English content before classification so keywords match
        try:
            from dedup_translate import translate_title as _translate
            title_en = _translate(title)
            summary_en = _translate(summary[:300]) if summary else ""
        except Exception:
            title_en, summary_en = title, summary
        combined_en = f"{title_en} {summary_en}"

        region_hint = source_cfg.get("region_hint")
        region, kw_region = _classify_region(combined_en, region_hint)
        severity, raw_conf = _classify_severity(combined_en)
        confidence = _apply_confidence_band(raw_conf, source_cfg["category"])

        # Store the English title; keep original in description for reference
        display_title = title_en if title_en != title else title
        event = GeoThreatEvent(
            source=source_cfg["name"],
            source_category=source_cfg["category"],
            title=display_title,
            description=summary_en or summary,
            url=url,
            region=region,
            severity=severity,
            keywords_matched=kw_region[:6],
            confidence=confidence,
            timestamp=pub_ts,
        )
        events.append(event)
    return events


class GeoThreatPipeline:
    """Async OSINT ingestion pipeline for open RSS/Atom sources."""

    def __init__(self):
        self._events: deque[GeoThreatEvent] = deque(
            maxlen=settings.GEOTHREAT_MAX_EVENTS
        )
        self._seen_ids: set[str] = set()
        self._sources: dict[str, SourceStatus] = {
            cfg["name"]: SourceStatus(
                cfg["name"], cfg["url"], cfg["category"], cfg["reliability"]
            )
            for cfg in settings.RSS_SOURCES
        }
        self._total_ingested = 0
        self._ingest_count = 0
        self._last_ingest: str = ""
        self._load_state()

    async def _fetch_source(
        self,
        session: aiohttp.ClientSession,
        source_cfg: dict,
    ) -> list[GeoThreatEvent]:
        status = self._sources[source_cfg["name"]]
        status.last_checked = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()

        try:
            async with session.get(
                source_cfg["url"],
                timeout=aiohttp.ClientTimeout(total=settings.GEOTHREAT_REQUEST_TIMEOUT),
                headers={"User-Agent": "AeglosAnalytics/1.0 (+osint-research)"},
            ) as resp:
                latency = (time.monotonic() - t0) * 1000
                status.latency_ms = latency

                if resp.status != 200:
                    status.status = "error"
                    status.error_count += 1
                    logger.warning("%s returned HTTP %s", source_cfg["name"], resp.status)
                    return []

                raw = await resp.text()
        except Exception as exc:
            status.status = "error"
            status.error_count += 1
            logger.warning("Feed fetch failed for %s: %s", source_cfg["name"], exc)
            return []

        feed = feedparser.parse(raw)
        events = _parse_feed_entries(feed, source_cfg)
        status.status = "online"
        status.last_success = datetime.now(timezone.utc).isoformat()
        status.events_collected += len(events)
        return events

    async def ingest_all_sources(self) -> dict[str, Any]:
        """Fetch all configured RSS sources + BlueSky concurrently."""
        # RSS sources
        connector = aiohttp.TCPConnector(limit=20)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                self._fetch_source(session, cfg)
                for cfg in settings.RSS_SOURCES
            ]
            rss_results = await asyncio.gather(*tasks, return_exceptions=True)

        new_count = 0
        for result in rss_results:
            if isinstance(result, list):
                for event in result:
                    if event.event_id not in self._seen_ids:
                        self._seen_ids.add(event.event_id)
                        self._events.appendleft(event)
                        new_count += 1

        # BlueSky sources
        bsky_count = 0
        if BLUESKY_AVAILABLE and _bsky_collector is not None:
            try:
                raw_posts = await _bsky_collector.collect()
                for post in raw_posts:
                    event = self._bsky_post_to_event(post)
                    if event and event.event_id not in self._seen_ids:
                        self._seen_ids.add(event.event_id)
                        self._events.appendleft(event)
                        new_count += 1
                        bsky_count += 1
            except Exception as exc:
                logger.warning("BlueSky ingest error: %s", exc)

        self._total_ingested += new_count
        self._ingest_count += 1
        self._last_ingest = datetime.now(timezone.utc).isoformat()

        # Trim _seen_ids to match only events still in the bounded deque
        self._seen_ids &= {e.event_id for e in self._events}

        self._save_state()

        logger.info(
            "Ingested %d new events (RSS=%d, BlueSky=%d, total=%d)",
            new_count, new_count - bsky_count, bsky_count, self._total_ingested,
        )

        return {
            "new_events": new_count,
            "total_events": len(self._events),
            "total_ingested": self._total_ingested,
            "bluesky_events": bsky_count,
            "bluesky_auth": _bsky_collector.has_credentials if _bsky_collector else False,
            "timestamp": self._last_ingest,
        }

    def _bsky_post_to_event(self, post: dict) -> "GeoThreatEvent | None":
        """Convert a BlueSky raw post dict into a GeoThreatEvent."""
        text = post.get("text", "").strip()
        if not text:
            return None
        # Translate before classifying so region/severity keywords match
        try:
            from dedup_translate import translate_title as _translate
            text_en = _translate(text)
        except Exception:
            text_en = text
        region, kw_region = _classify_region(text_en)
        severity, raw_conf = _classify_severity(text_en)
        category = post.get("category", "search")
        confidence = _apply_confidence_band(raw_conf, category)
        source_label = f"BlueSky/{post['handle']}"
        return GeoThreatEvent(
            source=source_label,
            source_category=category,
            title=text_en[:200],
            description=text_en,
            url=post.get("url", ""),
            region=region,
            severity=severity,
            keywords_matched=kw_region[:6],
            confidence=confidence,
            timestamp=post.get("created_at"),
        )

    def _save_state(self) -> None:
        import json, os
        path = settings.PERSIST_EVENTS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w") as f:
                json.dump({"events": [e.to_dict() for e in self._events]}, f)
        except Exception as exc:
            logger.warning("Failed to save events: %s", exc)

    def _load_state(self) -> None:
        import json
        path = settings.PERSIST_EVENTS_FILE
        try:
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        except Exception as exc:
            logger.warning("Failed to load persisted events: %s", exc)
            return
        loaded = 0
        for ev_dict in data.get("events", []):
            try:
                ev = GeoThreatEvent(
                    source=ev_dict["source"],
                    source_category=ev_dict["source_category"],
                    title=ev_dict["title"],
                    description=ev_dict.get("description", ""),
                    url=ev_dict.get("url", ""),
                    region=ev_dict["region"],
                    severity=ev_dict["severity"],
                    keywords_matched=ev_dict.get("keywords_matched", []),
                    confidence=ev_dict.get("confidence", 0.5),
                    timestamp=ev_dict.get("timestamp"),
                )
                ev.event_id = ev_dict["event_id"]  # restore original ID (don't re-hash)
                if ev.event_id not in self._seen_ids:
                    self._events.append(ev)
                    self._seen_ids.add(ev.event_id)
                    loaded += 1
            except Exception:
                continue
        if loaded:
            logger.info("Loaded %d persisted events from disk", loaded)

    def get_recent_events(
        self,
        limit: int = 50,
        region: str = "",
        severity: str = "",
    ) -> list[dict]:
        events = list(self._events)
        if region:
            events = [e for e in events if e.region.lower() == region.lower()]
        if severity:
            events = [e for e in events if e.severity.lower() == severity.lower()]
        return [e.to_dict() for e in events[:limit]]

    def get_stories(
        self,
        limit: int = 100,
        region: str = "",
        severity: str = "",
        translate: bool = True,
    ) -> list[dict]:
        """
        Return deduplicated, story-clustered events.
        Multiple sources reporting the same story are merged into one entry.
        Non-English headlines are translated to English.
        """
        events = list(self._events)
        if region:
            events = [e for e in events if e.region.lower() == region.lower()]
        if severity:
            events = [e for e in events if e.severity.lower() == severity.lower()]

        if DEDUP_AVAILABLE and _cluster_events is not None:
            try:
                clusters = _cluster_events(events, translate=translate)
                return clusters[:limit]
            except Exception as exc:
                logger.warning("Story clustering failed, falling back to raw events: %s", exc)

        # Fallback: return raw events as singleton clusters
        return [
            {
                "cluster_id": e.event_id,
                "headline": e.title,
                "region": e.region,
                "severity": e.severity,
                "confidence": round(e.confidence, 3),
                "timestamp": e.timestamp,
                "sources": [e.source],
                "urls": [e.url],
                "source_categories": [e.source_category],
                "keywords_matched": e.keywords_matched,
                "event_count": 1,
                "multi_source": False,
            }
            for e in events[:limit]
        ]

    def get_statistics(self) -> dict[str, Any]:
        events = list(self._events)
        severity_counts: dict[str, int] = {}
        region_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}

        for e in events:
            severity_counts[e.severity] = severity_counts.get(e.severity, 0) + 1
            region_counts[e.region] = region_counts.get(e.region, 0) + 1
            source_counts[e.source] = source_counts.get(e.source, 0) + 1

        online = sum(
            1 for s in self._sources.values() if s.status == "online"
        )

        global_count = region_counts.pop("Global", 0)
        return {
            "total_events": len(events),
            "total_ingested": self._total_ingested,
            "ingest_cycles": self._ingest_count,
            "last_ingest": self._last_ingest,
            "sources_online": online,
            "sources_total": len(self._sources),
            "severity_distribution": severity_counts,
            "region_distribution": region_counts,   # Global excluded from charts
            "global_unclassified": global_count,    # reported separately
            "top_sources": dict(
                sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
        }

    def get_sources_status(self) -> list[dict]:
        return [s.to_dict() for s in self._sources.values()]

    def get_events_by_region(self) -> dict[str, list[dict]]:
        by_region: dict[str, list[dict]] = {}
        for event in self._events:
            by_region.setdefault(event.region, []).append(event.to_dict())
        # Keep only 20 most recent per region
        return {r: evs[:20] for r, evs in by_region.items()}

    def get_events_by_severity(self) -> dict[str, list[dict]]:
        by_severity: dict[str, list[dict]] = {}
        for event in self._events:
            by_severity.setdefault(event.severity, []).append(event.to_dict())
        return {s: evs[:20] for s, evs in by_severity.items()}

    def get_regional_analysis(self) -> list[dict]:
        region_data: dict[str, dict] = {}
        for event in self._events:
            r = event.region
            if r not in region_data:
                region_data[r] = {
                    "region": r,
                    "event_count": 0,
                    "critical": 0,
                    "high": 0,
                    "moderate": 0,
                    "low": 0,
                    "top_severity": "low",
                    "sources": set(),
                    "latest_event": "",
                }
            d = region_data[r]
            d["event_count"] += 1
            d[event.severity] += 1
            d["sources"].add(event.source)
            if not d["latest_event"]:
                d["latest_event"] = event.title

        # Determine dominant severity per region
        severity_order = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
        result = []
        for d in region_data.values():
            top = max(
                ("critical", "high", "moderate", "low"),
                key=lambda s: d.get(s, 0) * severity_order[s],
            )
            d["top_severity"] = top
            d["sources"] = list(d["sources"])
            result.append(d)

        # Sort by severity then count — push Global to end (it's a catch-all, not a region)
        named = [d for d in result if d["region"] != "Global"]
        global_entry = [d for d in result if d["region"] == "Global"]
        named.sort(
            key=lambda x: (
                severity_order.get(x["top_severity"], 0),
                x["event_count"],
            ),
            reverse=True,
        )
        return named + global_entry

    def get_forecast(self) -> dict:
        """Compute 72-hour threat forecast using Prophet-based ML engine."""
        events = list(self._events)
        if PROPHET_AVAILABLE:
            try:
                return compute_forecast(events)
            except Exception as exc:
                logger.warning("Prophet forecast failed, falling back: %s", exc)
        # ── Fallback: simple diurnal repeat ──────────────────────────────────
        import math
        now = datetime.now(timezone.utc)
        SEVERITY_WEIGHT = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
        hourly_score: list[float] = [0.0] * 24
        for e in events:
            try:
                ts = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
                hourly_score[ts.hour] += SEVERITY_WEIGHT.get(e.severity, 1)
            except Exception:
                continue
        max_score = max(hourly_score) if max(hourly_score) > 0 else 1
        base_pattern = [s / max_score for s in hourly_score]
        region_scores: dict[str, list[float]] = {}
        for e in events:
            region_scores.setdefault(e.region, []).append(SEVERITY_WEIGHT.get(e.severity, 1))
        region_risk = {}
        all_weights = [w for ws in region_scores.values() for w in ws]
        global_max = max(all_weights) if all_weights else 1
        for region, weights in region_scores.items():
            avg = sum(weights) / len(weights) / global_max if weights else 0
            region_risk[region] = round(min(avg, 1.0), 3)
        start_hour = now.hour
        forecast_points = []
        for i in range(72):
            h = (start_hour + i) % 24
            threat = base_pattern[h]
            decay = math.exp(-0.008 * i)
            conf = round(max(0.03, decay * 0.97), 4)
            band = (1 - conf) * 0.35
            forecast_points.append({
                "hour": f"+{i}h",
                "threat": round(threat * decay, 4),
                "upper": round(min(threat * decay + band, 1.0), 4),
                "lower": round(max(threat * decay - band, 0.0), 4),
                "confidence": conf,
            })
        return {
            "points": forecast_points,
            "region_risk": region_risk,
            "total_events_used": len(events),
            "generated_at": now.isoformat(),
        }

    def get_patterns(self) -> dict:
        """Compute activity patterns using Prophet decomposition."""
        events = list(self._events)
        if PROPHET_AVAILABLE:
            try:
                return compute_patterns(events)
            except Exception as exc:
                logger.warning("Prophet patterns failed, falling back: %s", exc)
        # ── Fallback: simple hour-of-day buckets ─────────────────────────────
        SEVERITY_WEIGHT = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
        hourly_count = [0] * 24
        hourly_score = [0.0] * 24
        day_count = [0] * 7
        source_cat_times: dict[str, list[str]] = {}
        sev_dist: dict[str, int] = {}
        for e in events:
            sev_dist[e.severity] = sev_dist.get(e.severity, 0) + 1
            try:
                ts = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
                hourly_count[ts.hour] += 1
                hourly_score[ts.hour] += SEVERITY_WEIGHT.get(e.severity, 1)
                day_count[ts.weekday()] += 1
            except Exception:
                continue
            source_cat_times.setdefault(e.source_category, []).append(e.timestamp)
        peak_hour = hourly_count.index(max(hourly_count)) if any(hourly_count) else 0
        detected = []
        if any(hourly_count):
            detected.append({
                "name": "Diurnal Activity Peak",
                "confidence": round(min(0.60 + 0.01 * len(events), 0.97), 2),
                "desc": f"Event volume peaks at {peak_hour:02d}:00 UTC ({hourly_count[peak_hour]} events).",
            })
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return {
            "hourly_count": [{"hour": f"{h:02d}:00", "count": hourly_count[h], "score": round(hourly_score[h], 1)} for h in range(24)],
            "daily_count": [{"day": days[d], "count": day_count[d]} for d in range(7)],
            "severity_distribution": sev_dist,
            "detected_patterns": detected,
            "total_events_used": len(events),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_correlation(self) -> dict:
        """Compute cross-region correlation using aligned hourly time-series vectors."""
        events = list(self._events)
        if PROPHET_AVAILABLE:
            try:
                return compute_correlation_matrix(events)
            except Exception as exc:
                logger.warning("Prophet correlation failed, falling back: %s", exc)
        # ── Fallback: hour-of-day Pearson ────────────────────────────────────
        import math
        regions = list({e.region for e in events})
        sources = list({e.source for e in events})
        SEVERITY_WEIGHT = {"critical": 4, "high": 3, "moderate": 2, "low": 1}

        def region_vector(region: str) -> list[float]:
            v = [0.0] * 24
            for e in events:
                if e.region == region:
                    try:
                        h = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00")).hour
                        v[h] += SEVERITY_WEIGHT.get(e.severity, 1)
                    except Exception:
                        pass
            return v

        def pearson(a: list[float], b: list[float]) -> float:
            n = len(a)
            mean_a = sum(a) / n
            mean_b = sum(b) / n
            num = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
            den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
            den_b = math.sqrt(sum((x - mean_b) ** 2 for x in b))
            if den_a == 0 or den_b == 0:
                return 0.0
            return round(num / (den_a * den_b), 3)

        top_regions = sorted(
            [r for r in regions if r != "Global"],
            key=lambda r: sum(1 for e in events if e.region == r),
            reverse=True,
        )
        vectors = {r: region_vector(r) for r in top_regions}
        matrix = [{"region": r1, "values": [pearson(vectors[r1], vectors[r2]) for r2 in top_regions]} for r1 in top_regions]
        top_sources = sorted(sources, key=lambda s: sum(1 for e in events if e.source == s), reverse=True)
        heatmap = [{"source": src, "regions": {r: sum(1 for e in events if e.source == src and e.region == r) for r in top_regions}} for src in top_sources]
        return {
            "regions": top_regions,
            "correlation_matrix": matrix,
            "source_heatmap": heatmap,
            "total_events_used": len(events),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


# Module-level singleton
pipeline = GeoThreatPipeline()
