# AEGLOS Analytics Pro — Live Data Setup

## Quick Start (Free, No API Keys)

The system works immediately with 9 RSS feeds:

```bash
./start-dev.sh
# Open http://localhost:5000/geothreat
# Dashboard auto-detects API → shows 🔴 LIVE MODE
```

Trigger a manual collection:
```bash
curl -X POST http://localhost:8000/api/v1/geothreat/ingest
```

Check collection statistics:
```bash
curl http://localhost:8000/api/v1/geothreat/statistics | python3 -m json.tool
```

Check source status:
```bash
curl http://localhost:8000/api/v1/geothreat/sources | python3 -m json.tool
```

---

## RSS Feed Configuration

Feeds are defined in `config.py` under `RSS_SOURCES`. Each entry:

```python
{
    "name": "AP News - World",
    "url": "https://feeds.apnews.com/rss/apf-worldnews",
    "category": "news",       # news | government | regional
    "reliability": 0.97,      # 0.0-1.0 source reliability score
}
```

To add a custom feed, append to the list in `config.py`.

---

## Optional API Key Setup

### News API (newsapi.org)
Adds 50+ news sources with keyword search:
```bash
export NEWS_API_KEY="your-key-here"
# Then in config.py, add feeds from newsapi.org
```

### Twitter/X Academic API
```bash
export TWITTER_BEARER_TOKEN="your-token"
# Enables social media HUMINT indicators
```

### ACLED API (free registration)
```bash
export ACLED_API_KEY="your-key"
export ACLED_EMAIL="your@email.com"
# Enables ACLED conflict event data
```

---

## Testing Feed Collection

```bash
# Test single feed manually
python3 -c "
import feedparser
feed = feedparser.parse('https://feeds.apnews.com/rss/apf-worldnews')
print(f'AP News: {len(feed.entries)} entries')
for e in feed.entries[:3]:
    print(f'  - {e.title[:60]}')
"

# Test the full pipeline
python3 -c "
import asyncio
from geothreat_pipeline import pipeline
result = asyncio.run(pipeline.ingest_all_sources())
print(result)
"
```

---

## Configuration Options

In `config.py`:

```python
GEOTHREAT_POLL_INTERVAL = 300    # Seconds between auto-refreshes
GEOTHREAT_MAX_EVENTS = 10_000    # Max events to buffer
GEOTHREAT_REQUEST_TIMEOUT = 15   # Per-feed request timeout (seconds)
```

---

## Troubleshooting

**Feed returns 0 events**: Some feeds may be temporarily down or have changed URLs. Check `sources_status` endpoint.

**"Connection refused" from dashboard**: API server not running. Run `./start-dev.sh` or check `logs/api.log`.

**DEMO MODE showing instead of LIVE**: API health check failed. Verify API is on port 8000: `curl http://localhost:8000/health`

**Slow initial load**: First ingest triggers ML training (takes ~10s). Subsequent requests are fast.

**Feed blocked (403)**: Some feeds block certain User-Agent strings. The pipeline sends `AeglosAnalytics/1.0 (+osint-research)` which is generally accepted.
