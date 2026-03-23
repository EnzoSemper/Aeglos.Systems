# AEGLOS Analytics Pro — 60-Second Quick Start

```bash
# 1. Navigate to project
cd ~/aeglos-analytics

# 2. Start everything
./start-dev.sh

# 3. Open intelligence dashboard
open http://localhost:5000/geothreat
# → Shows 🔴 LIVE MODE with real RSS data

# 4. Trigger first collection (auto-done at startup)
curl -X POST http://localhost:8000/api/v1/geothreat/ingest

# 5. View events
curl http://localhost:8000/api/v1/geothreat/events | python3 -m json.tool

# 6. Stop
./stop.sh
```

That's it. No API keys, no configuration.
