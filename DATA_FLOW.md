# AEGLOS Analytics Pro — Data Flow Architecture

## 6-Stage Pipeline

```
Stage 1: COLLECTION
  RSS Feeds (9 active) → aiohttp async fetch → feedparser parse
  ↓
Stage 2: NORMALIZATION
  Text extraction → Unicode normalization → length capping
  Field standardization (timestamp, title, description, url)
  ↓
Stage 3: CLASSIFICATION
  Region detection  → keyword match against 8 region sets
  Severity scoring  → keyword match against 4 severity tiers
  Confidence calc   → scaled by keyword hit count
  Deduplication     → SHA-1 hash of source+title+url
  ↓
Stage 4: ANALYSIS
  IsolationForest   → anomaly score per event
  RandomForest      → threat class (0-4)
  Feature extract   → 8-dim vector per event
  ↓
Stage 5: FUSION
  Circular buffer   → deque(maxlen=10,000) most recent events
  Region aggregation → event counts, severity distribution
  Source tracking   → status, latency, error counts
  ↓
Stage 6: DISSEMINATION
  REST API          → FastAPI endpoints, JSON responses
  Web dashboards    → Chart.js visualizations, live polling
  SDK               → aeglos_client.py Python wrapper
  Alerts            → Critical/High events surfaced to UI
```

## Latency Budget

| Stage | Typical Latency |
|-------|----------------|
| RSS Fetch (9 sources, async) | 200–800ms |
| Parse + Classify | <5ms per event |
| ML Analysis | <50ms per batch |
| API Response | <20ms |
| Dashboard Poll | Every 30s |

## Data Model

```python
GeoThreatEvent:
  event_id:         str   # SHA-1(source+title+url)[:16]
  timestamp:        str   # ISO 8601 UTC
  source:           str   # Feed name
  source_category:  str   # news | government | regional
  title:            str   # Article headline
  description:      str   # First 500 chars of summary
  url:              str   # Original article URL
  region:           str   # One of 8 geographic regions
  severity:         str   # critical | high | moderate | low
  keywords_matched: list  # Top 6 matching keywords
  confidence:       float # 0.50–0.99
```
