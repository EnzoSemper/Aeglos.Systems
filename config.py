"""
AEGLOS Analytics Pro - System Configuration
HUMINT/OSINT/GEOINT Intelligence Fusion Platform
"""

import os
from pathlib import Path


class Settings:
    APP_NAME = "AEGLOS Analytics Pro"
    VERSION = "1.0.0"
    API_PREFIX = "/api/v1"
    HOST = os.getenv("API_HOST", "0.0.0.0")
    PORT = int(os.getenv("API_PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # Processing performance targets
    MAX_DATA_POINTS_PER_SEC = 10_000_000
    PROCESSING_WORKERS = int(os.getenv("WORKERS", "4"))
    BATCH_SIZE = 1000
    BUFFER_SIZE = 10_000

    # ML targets
    MODEL_ACCURACY_TARGET = 0.997
    FORECAST_HOURS = 72
    ANOMALY_CONTAMINATION = 0.05

    # Latency targets
    LATENCY_TARGET_MS = 50

    # Security
    ENCRYPTION_ITERATIONS = 100_000
    TOKEN_LENGTH = 32

    # GeoThreat OSINT
    GEOTHREAT_POLL_INTERVAL = 300       # seconds between feed refreshes
    GEOTHREAT_MAX_EVENTS = 10_000
    GEOTHREAT_REQUEST_TIMEOUT = 15      # seconds per feed request

    # Database (optional)
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Authentication — set AEGLOS_API_KEY env var to enable; empty = auth disabled (dev)
    AEGLOS_API_KEY: str = os.getenv("AEGLOS_API_KEY", "")

    # CORS — comma-separated list of allowed origins; defaults to wildcard (dev)
    _cors_raw: str = os.getenv("CORS_ORIGINS", "")
    CORS_ORIGINS: list = [o.strip() for o in _cors_raw.split(",") if o.strip()] or ["*"]

    # Persistence — directory for event/state JSON files
    PERSIST_DIR: str = os.getenv(
        "AEGLOS_PERSIST_DIR",
        str(Path.home() / "Library" / "Application Support" / "AEGLOS" / "state"),
    )
    PERSIST_EVENTS_FILE: str = str(Path(PERSIST_DIR) / "events.json")
    PERSIST_SOCIAL_FILE: str = str(Path(PERSIST_DIR) / "social_config.json")

    # RSS Feed Sources (verified live)
    # region_hint: fallback region when no keyword matches — avoids flooding "Global"
    RSS_SOURCES = [
        # ── Global News ───────────────────────────────────────────────────────
        {
            "name": "The Guardian - World",
            "url": "https://www.theguardian.com/world/rss",
            "category": "news",
            "reliability": 0.95,
            "region_hint": None,   # truly global; keep as Global if no match
        },
        {
            "name": "BBC News - World",
            "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
            "category": "news",
            "reliability": 0.96,
            "region_hint": None,
        },
        {
            "name": "Sky News - World",
            "url": "https://feeds.skynews.com/feeds/rss/world.xml",
            "category": "news",
            "reliability": 0.94,
            "region_hint": None,
        },
        {
            "name": "Al Jazeera - News",
            "url": "https://www.aljazeera.com/xml/rss/all.xml",
            "category": "news",
            "reliability": 0.88,
            "region_hint": "Middle East",   # heavy ME focus
        },
        {
            "name": "TASS - News",
            "url": "https://tass.com/rss/v2.xml",
            "category": "news",
            "reliability": 0.72,
            "region_hint": "Eastern Europe",
        },
        {
            "name": "Xinhua - World",
            "url": "http://www.xinhuanet.com/english/rss/worldnews.xml",
            "category": "news",
            "reliability": 0.70,
            "region_hint": "East Asia",
        },
        # ── Asia-Pacific ──────────────────────────────────────────────────────
        {
            "name": "NHK World - News",
            "url": "https://www3.nhk.or.jp/rss/news/cat0.xml",
            "category": "news",
            "reliability": 0.95,
            "region_hint": "East Asia",
        },
        {
            "name": "Straits Times - Asia",
            "url": "https://www.straitstimes.com/news/asia/rss.xml",
            "category": "news",
            "reliability": 0.93,
            "region_hint": "Southeast Asia",
        },
        {
            "name": "Channel NewsAsia - World",
            "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
            "category": "news",
            "reliability": 0.92,
            "region_hint": "Southeast Asia",
        },
        {
            "name": "ABC Australia - World",
            "url": "https://www.abc.net.au/news/feed/51120/rss.xml",
            "category": "news",
            "reliability": 0.94,
            "region_hint": "Australia & Pacific",
        },
        {
            "name": "Sydney Morning Herald - World",
            "url": "https://www.smh.com.au/rss/world.xml",
            "category": "news",
            "reliability": 0.93,
            "region_hint": "Australia & Pacific",
        },
        # ── Government / Official ─────────────────────────────────────────────
        {
            "name": "FBI - Press Releases",
            "url": "https://www.fbi.gov/feeds/fbi-in-the-news/rss.xml",
            "category": "government",
            "reliability": 0.99,
            "region_hint": "Americas",
        },
        {
            "name": "DoD - News",
            "url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=10",
            "category": "government",
            "reliability": 0.99,
            "region_hint": None,   # DoD covers global operations
        },
        {
            "name": "OCHA - Humanitarian Affairs",
            "url": "https://www.unocha.org/rss.xml",
            "category": "government",
            "reliability": 0.96,
            "region_hint": None,
        },
        {
            "name": "Crisis Group - ICG",
            "url": "https://www.crisisgroup.org/rss.xml",
            "category": "analysis",
            "reliability": 0.95,
            "region_hint": None,
        },
        {
            "name": "UN News - Global",
            "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
            "category": "government",
            "reliability": 0.96,
            "region_hint": None,   # UN covers everything — keep Global if no match
        },
        {
            "name": "Foreign Policy",
            "url": "https://foreignpolicy.com/feed/",
            "category": "analysis",
            "reliability": 0.92,
            "region_hint": None,
        },
    ]

    # Region keyword mapping
    REGION_KEYWORDS = {
        "Middle East": [
            "iran", "iraq", "syria", "israel", "palestine", "gaza", "west bank",
            "lebanon", "jordan", "saudi", "yemen", "oman", "uae", "qatar",
            "bahrain", "kuwait", "hezbollah", "hamas", "houthi", "persian gulf",
            "red sea", "suez", "tehran", "baghdad", "damascus", "beirut",
        ],
        "Southeast Asia": [
            "philippines", "vietnam", "thailand", "malaysia", "indonesia",
            "singapore", "myanmar", "cambodia", "laos", "brunei", "timor-leste",
            "south china sea", "spratly", "paracel", "manila", "hanoi",
            "jakarta", "kuala lumpur", "bangkok", "rangoon", "naypyidaw",
            "phnom penh", "vientiane", "ho chi minh", "asean",
            "rohingya", "strait of malacca", "celebes sea", "sulu sea",
            "abu sayyaf", "nia", "jemaah islamiyah",
        ],
        "Australia & Pacific": [
            "australia", "new zealand", "papua new guinea", "solomon islands",
            "vanuatu", "fiji", "tonga", "samoa", "kiribati", "tuvalu",
            "micronesia", "marshall islands", "palau", "nauru",
            "sydney", "melbourne", "canberra", "auckland", "wellington",
            "port moresby", "suva", "adf", "australian defence",
            "aukus", "quad", "asio", "asis", "pacific islands forum",
            "coral sea", "tasman sea", "indo-pacific",
        ],
        "Eastern Europe": [
            "ukraine", "russia", "poland", "belarus", "moldova", "georgia",
            "armenia", "azerbaijan", "nato", "kyiv", "moscow", "donbas",
            "crimea", "kharkiv", "odessa", "zaporizhzhia", "budapest",
            "warsaw", "bucharest", "baltic", "estonia", "latvia", "lithuania",
        ],
        "East Asia": [
            "china", "taiwan", "north korea", "south korea", "japan",
            "hong kong", "tibet", "xinjiang", "dprk", "pla", "prc",
            "beijing", "seoul", "tokyo", "pyongyang", "strait of taiwan",
            "senkaku", "diaoyu",
        ],
        "South Asia": [
            "india", "pakistan", "afghanistan", "bangladesh", "sri lanka",
            "nepal", "bhutan", "kashmir", "line of control", "new delhi",
            "islamabad", "kabul", "dhaka",
        ],
        "Africa": [
            "nigeria", "ethiopia", "somalia", "sudan", "libya", "mali",
            "burkina faso", "mozambique", "congo", "drc", "sahel",
            "boko haram", "al-shabaab", "wagner", "dakar", "nairobi",
            "addis ababa", "tripoli", "khartoum",
        ],
        "Americas": [
            "venezuela", "colombia", "mexico", "haiti", "cuba", "nicaragua",
            "cartel", "farc", "narco", "maduro", "caracas", "bogota",
            "port-au-prince", "central america", "latin america",
        ],
        "Global": [],  # fallback
    }

    # Severity keyword mapping
    # critical = confirmed armed actions, new active threats
    # high     = military/government movements, open conflict
    # moderate = geopolitical/economic tensions, extremist rhetoric
    # low      = minor criminal activity, small-scale incidents
    SEVERITY_KEYWORDS = {
        "critical": [
            "killed", "kill", "kills", "killing", "casualties", "dead", "death toll", "wounded",
            "bombing", "bombed", "explosion", "exploded", "missile strike", "airstrike", "airstrikes",
            "rocket attack", "strikes kill", "attack kills",
            "invasion", "invaded", "occupied", "offensive launched", "ground assault",
            "coup", "assassinat", "assassinated", "executed",
            "nuclear", "chemical weapon", "biological weapon", "dirty bomb",
            "mass destruction", "wmd",
            "terrorist attack", "suicide bomb", "car bomb", "hostage",
            "genocide", "massacre", "ethnic cleansing", "civil war",
            "armed attack", "confirmed strike", "active shooter",
            "dead in", "people dead", "people killed", "people wounded",
            "drone strike", "drone attack", "drone strikes",
        ],
        "high": [
            "military operation", "troops deployed", "forces mobilized",
            "troop movement", "troop buildup", "military exercises",
            "warship", "aircraft carrier", "fighter jet", "submarine",
            "government forces", "rebel forces", "armed group",
            "open conflict", "clashes", "firefight", "shelling",
            "blockade", "siege", "no-fly zone",
            "sanctions imposed", "embargo", "asset freeze",
            "state of emergency", "martial law", "curfew",
            "military coup", "putsch", "overthrow",
            "nuclear program", "ballistic missile", "hypersonic",
            "escalation", "incursion", "border crossing", "aggression",
            "nato alert", "defense readiness",
            "military strike", "strikes", "bombing campaign",
            "attacks", "attack on", "assault on", "drones attack",
        ],
        "moderate": [
            "oil price", "gas price", "fuel price", "energy crisis",
            "opec", "petroleum", "natural gas supply", "pipeline",
            "jihad", "extremist", "radicalization", "terror threat",
            "threat of attack", "militant rhetoric",
            "threatens", "retaliatory", "retaliation", "warns", "warning",
            "espionage", "spy charges", "expulsion",
            "protest", "demonstration", "riot", "civil unrest",
            "diplomatic tension", "expel ambassador", "recall ambassador",
            "sanctions threat", "trade war", "tariff",
            "election fraud", "political crisis", "government collapse",
            "standoff", "dispute", "condemn", "accusation",
            "opposition", "strike", "walkout", "rally",
            "economic collapse", "inflation", "food shortage",
            "cyberattack", "hacking", "data breach", "infrastructure attack",
        ],
        "low": [
            "drug trafficking", "drug bust", "narcotics",
            "illicit", "smuggling", "contraband",
            "gang", "cartel activity", "organized crime",
            "minor incident", "arrest", "detained",
            "border patrol", "immigration",
        ],
    }

    CLASSIFICATION = "UNCLASSIFIED // FOR OFFICIAL USE ONLY"
    ORIGINATOR = "AEGLOS Analytics Pro v1.0"


settings = Settings()
