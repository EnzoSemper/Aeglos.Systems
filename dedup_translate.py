"""
AEGLOS Analytics Pro — Deduplication, Story Clustering & Translation

Two responsibilities:
1. translate_title(text) — translates non-English headlines to English using
   Google Translate's public endpoint (no API key required).
2. cluster_events(events) — groups near-duplicate events (same story from
   multiple sources) into StoryCluster objects using trigram Jaccard similarity.
   Returns a list of StoryCluster dicts ready for the API response.
"""

import hashlib
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("dedup_translate")

# ── Configuration ─────────────────────────────────────────────────────────────
JACCARD_THRESHOLD = 0.30      # titles with trigram Jaccard >= this are same story
CLUSTER_MAX_AGE_H = 48        # ignore events older than this for clustering
TRANSLATE_TIMEOUT  = 5        # seconds; translation is best-effort
TRANSLATE_CACHE_TTL = 3600    # seconds before cached translation expires

# ── Translation cache (in-memory, bounded) ───────────────────────────────────
_trans_cache: dict[str, tuple[str, float]] = {}  # text → (translated, expires)
_CACHE_MAX = 2000


def _trigrams(text: str) -> set[str]:
    """Character-level 3-grams of a normalised string."""
    t = re.sub(r"\s+", " ", text.lower().strip())
    return {t[i:i+3] for i in range(len(t) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _title_key(title: str) -> str:
    """Stable fingerprint used as cluster seed key."""
    normalised = re.sub(r"\s+", " ", title.lower().strip())[:120]
    return hashlib.sha1(normalised.encode()).hexdigest()[:12]


# Common stop words for non-English languages that use mostly ASCII letters.
# If any of these appear in text, flag as non-English for translation.
_LATIN_NONEN_STOPWORDS = frozenset([
    # French
    "le", "la", "les", "de", "du", "des", "un", "une", "est", "sont",
    "dans", "sur", "avec", "pour", "par", "une", "qui", "que", "cette",
    "ses", "leur", "leurs", "mais", "aussi", "après", "avant", "entre",
    "annonce", "selon", "lors", "contre", "face", "vers", "déclare",
    # French news/conflict vocabulary
    "frappe", "frappes", "mort", "morts", "moins", "plus", "font",
    "dont", "guerre", "armée", "quand", "donc", "tout", "très",
    "nous", "vous", "elles", "leur", "ont", "été", "faire", "fait",
    "nouveau", "nouvelle", "nouvelles", "premier", "première",
    "ministre", "gouvernement", "forces", "soldats", "civil", "civils",
    "attaque", "attaques", "tirs", "frappe", "blessés", "victimes",
    # Spanish
    "el", "los", "las", "del", "una", "son", "con", "por", "como",
    "más", "sobre", "sus", "también", "según", "ante", "tras", "entre",
    "gobierno", "presidente", "ministro", "fuerza", "ataque",
    # German
    "die", "der", "das", "und", "ist", "mit", "von", "auf", "für",
    "aus", "nach", "wird", "haben", "sein", "nicht", "auch", "bei",
    "zum", "zur", "des", "den", "russland", "ukraine", "greift",
    "angriff", "drohnen", "bundeswehr", "nato", "städte", "gegen",
    # Portuguese
    "os", "as", "um", "uma", "para", "por", "com", "não", "está",
    "são", "seu", "sua", "mas", "sobre", "entre", "após", "governo",
    # Italian
    "gli", "del", "della", "dello", "delle", "degli", "con", "per",
    "nel", "nella", "negli", "nelle", "dal", "dalla",
])


def _is_likely_non_english(text: str) -> bool:
    """
    Detect non-English text using two strategies:
    1. Low ASCII-alpha ratio → catches Cyrillic, Arabic, CJK, etc.
    2. Non-English stop words → catches French, Spanish, German, etc.
    """
    if not text:
        return False

    # Strategy 1: non-ASCII script ratio
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha > 0 and (ascii_alpha / total_alpha) < 0.70:
        return True

    # Strategy 2: Latin-script non-English stop words
    # Require 2+ hits to reduce false positives on short English text
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", text.lower())
    hits = sum(1 for w in words if w in _LATIN_NONEN_STOPWORDS)
    return hits >= 2


def translate_title(text: str) -> str:
    """
    Translate text to English using Google Translate's public endpoint.
    Returns original text on any failure (translation is best-effort).
    Caches results to avoid redundant requests.
    """
    if not text or not _is_likely_non_english(text):
        return text

    now = time.monotonic()

    # Check cache
    cached = _trans_cache.get(text)
    if cached and cached[1] > now:
        return cached[0]

    try:
        # Google Translate unofficial/public endpoint — no API key needed
        params = urllib.parse.urlencode({
            "client": "gtx",
            "sl":     "auto",
            "tl":     "en",
            "dt":     "t",
            "q":      text,
        })
        url = f"https://translate.googleapis.com/translate_a/single?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TRANSLATE_TIMEOUT) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            # Response structure: [[["translated","original",...],...],...]
            parts = []
            for block in data[0]:
                if block and block[0]:
                    parts.append(block[0])
            translated = "".join(parts).strip() or text

        # Evict oldest entries if cache is full
        if len(_trans_cache) >= _CACHE_MAX:
            oldest_key = min(_trans_cache, key=lambda k: _trans_cache[k][1])
            del _trans_cache[oldest_key]

        _trans_cache[text] = (translated, now + TRANSLATE_CACHE_TTL)
        if translated != text:
            logger.debug("Translated: %r → %r", text[:60], translated[:60])
        return translated

    except Exception as exc:
        logger.debug("Translation failed for %r: %s", text[:40], exc)
        return text


# ── Story Clustering ──────────────────────────────────────────────────────────

class StoryCluster:
    """
    A group of events that describe the same underlying news story.
    The cluster exposes a single compiled headline and aggregates
    source attributions.
    """
    __slots__ = (
        "cluster_id", "headline", "region", "severity", "confidence",
        "timestamp", "sources", "urls", "keywords_matched",
        "source_categories", "event_count",
    )

    def __init__(self, seed_event: Any):
        self.cluster_id: str = _title_key(seed_event.title)
        self.headline: str = seed_event.title         # English headline (may be translated)
        self.region: str = seed_event.region
        self.severity: str = seed_event.severity
        self.confidence: float = seed_event.confidence
        self.timestamp: str = seed_event.timestamp
        self.sources: list[str] = [seed_event.source]
        self.urls: list[str] = [seed_event.url] if seed_event.url else []
        self.keywords_matched: list[str] = list(seed_event.keywords_matched)
        self.source_categories: set[str] = {seed_event.source_category}
        self.event_count: int = 1

    def merge(self, event: Any) -> None:
        """Absorb an additional event into this cluster."""
        self.event_count += 1
        if event.source not in self.sources:
            self.sources.append(event.source)
        if event.url and event.url not in self.urls:
            self.urls.append(event.url)
        self.source_categories.add(event.source_category)
        # Upgrade severity if higher
        _SEV_RANK = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
        if _SEV_RANK.get(event.severity, 0) > _SEV_RANK.get(self.severity, 0):
            self.severity = event.severity
        # Confidence: take maximum (most authoritative source wins)
        if event.confidence > self.confidence:
            self.confidence = event.confidence
            self.headline = event.title   # better headline from higher-confidence source
        # Use the earliest timestamp (when story first broke)
        try:
            ts_existing = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            ts_new = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            if ts_new < ts_existing:
                self.timestamp = event.timestamp
        except Exception:
            pass
        # Merge keywords
        for kw in event.keywords_matched:
            if kw not in self.keywords_matched:
                self.keywords_matched.append(kw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "headline": self.headline,
            "region": self.region,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "timestamp": self.timestamp,
            "sources": self.sources,
            "urls": self.urls[:5],           # cap at 5 URLs
            "source_categories": sorted(self.source_categories),
            "keywords_matched": self.keywords_matched[:8],
            "event_count": self.event_count,
            "multi_source": self.event_count >= 3,
        }


def cluster_events(events: list[Any], translate: bool = True) -> list[dict]:
    """
    Given a list of GeoThreatEvent objects:
      1. Optionally translate non-English titles to English.
      2. Group near-duplicate events (same story) using trigram Jaccard.
      3. Return clusters sorted by (severity rank DESC, event_count DESC, timestamp DESC).

    Only events from within the last CLUSTER_MAX_AGE_H hours are clustered;
    older events are included as singletons.
    """
    if not events:
        return []

    now = datetime.now(timezone.utc)
    _SEV_RANK = {"critical": 4, "high": 3, "moderate": 2, "low": 1}

    # Step 1: Titles are already translated at ingest time; this pass is a
    # safety net for any remaining non-English content (e.g. from future sources).
    titles: dict[str, str] = {}   # event_id → possibly-translated title
    for e in events:
        t = e.title
        if translate and _is_likely_non_english(t):
            try:
                t = translate_title(t)
            except Exception:
                pass
        titles[e.event_id] = t

    # Step 2: Filter to recent events for clustering
    recent, old = [], []
    for e in events:
        try:
            ts = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00"))
            age_h = (now - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else now - ts).total_seconds() / 3600
        except Exception:
            age_h = 0
        (recent if age_h <= CLUSTER_MAX_AGE_H else old).append(e)

    # Step 3: Cluster recent events
    clusters: list[StoryCluster] = []
    cluster_trigrams: list[set[str]] = []

    for e in recent:
        title = titles[e.event_id]
        tg = _trigrams(title)
        best_idx, best_score = -1, 0.0

        for idx, ctg in enumerate(cluster_trigrams):
            score = _jaccard(tg, ctg)
            if score > best_score:
                best_score, best_idx = score, idx

        if best_score >= JACCARD_THRESHOLD and best_idx >= 0:
            clusters[best_idx].merge(e)
            # Update cluster trigrams to reflect merged headline
            cluster_trigrams[best_idx] = _trigrams(clusters[best_idx].headline)
        else:
            # New cluster — use translated title as headline
            seed = e
            c = StoryCluster(seed)
            c.headline = title
            clusters.append(c)
            cluster_trigrams.append(tg)

    # Step 4: Add old events as singletons
    for e in old:
        c = StoryCluster(e)
        c.headline = titles[e.event_id]
        clusters.append(c)

    # Step 5: Sort — critical multi-source first, then by recency
    clusters.sort(
        key=lambda c: (
            -_SEV_RANK.get(c.severity, 0),
            -c.event_count,
            c.timestamp,
        )
    )

    return [c.to_dict() for c in clusters]
