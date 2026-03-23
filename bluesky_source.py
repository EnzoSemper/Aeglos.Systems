"""
AEGLOS Analytics Pro — BlueSky/AT Protocol OSINT Collector

Account monitoring works with NO credentials (public API).
Keyword search requires a free BlueSky account + app password:
  BLUESKY_IDENTIFIER=you.bsky.social
  BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

logger = logging.getLogger("bluesky")

BSKY_PUBLIC  = "https://public.api.bsky.app/xrpc"
BSKY_API     = "https://bsky.social/xrpc"
SESSION_TTL  = 3600   # re-auth after 1 hour
REQUEST_TIMEOUT = 12  # seconds


# ── Accounts to monitor (no auth required) ────────────────────────────────────
MONITORED_ACCOUNTS = [
    # Newswires
    {"handle": "reuters.com",        "category": "news",    "reliability": 0.96},
    {"handle": "apnews.com",         "category": "news",    "reliability": 0.97},
    {"handle": "theguardian.com",    "category": "news",    "reliability": 0.95},
    {"handle": "aljazeera.com",      "category": "news",    "reliability": 0.88},
    # Policy / Analysis
    {"handle": "foreignpolicy.com",  "category": "analysis","reliability": 0.92},
    {"handle": "theatlantic.com",    "category": "analysis","reliability": 0.90},
    {"handle": "brookings.edu",      "category": "analysis","reliability": 0.93},
    {"handle": "rand.org",           "category": "analysis","reliability": 0.94},
    # Investigative / OSINT
    {"handle": "bellingcat.com",     "category": "osint",   "reliability": 0.95},
    {"handle": "propublica.org",     "category": "osint",   "reliability": 0.94},
    {"handle": "icij.org",           "category": "osint",   "reliability": 0.93},
    # Other
    {"handle": "axios.com",          "category": "news",    "reliability": 0.91},
    {"handle": "politico.com",       "category": "news",    "reliability": 0.90},
    {"handle": "lemonde.fr",         "category": "news",    "reliability": 0.89},
]

# ── Keyword searches (requires auth) ─────────────────────────────────────────
SEARCH_QUERIES = [
    "military strike",
    "airstrike casualties",
    "troop deployment",
    "missile attack",
    "armed conflict",
    "coup attempt",
    "sanctions imposed",
    "naval confrontation",
    "terrorist attack",
    "nuclear threat",
    "south china sea",
    "ukraine russia",
    "iran israel",
    "north korea missile",
    "taiwan strait",
]


class BlueSkyCollector:
    def __init__(self):
        self._access_jwt: str = ""
        self._session_ts: float = 0.0
        self._identifier = os.getenv("BLUESKY_IDENTIFIER", "")
        self._app_password = os.getenv("BLUESKY_APP_PASSWORD", "")
        self._authed = False
        self._seen_uris: set[str] = set()
        # Per-account cursor tracking for incremental fetches
        self._cursors: dict[str, str] = {}

    @property
    def has_credentials(self) -> bool:
        return bool(self._identifier and self._app_password)

    async def _authenticate(self, session: aiohttp.ClientSession) -> bool:
        """Create an authenticated session. Returns True on success."""
        if not self.has_credentials:
            return False
        try:
            async with session.post(
                f"{BSKY_API}/com.atproto.server.createSession",
                json={"identifier": self._identifier, "password": self._app_password},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    logger.warning("BlueSky auth failed: HTTP %s", resp.status)
                    return False
                data = await resp.json()
                self._access_jwt = data.get("accessJwt", "")
                self._session_ts = time.monotonic()
                self._authed = bool(self._access_jwt)
                logger.info("BlueSky authenticated as %s", self._identifier)
                return self._authed
        except Exception as exc:
            logger.warning("BlueSky auth error: %s", exc)
            return False

    async def _ensure_auth(self, session: aiohttp.ClientSession) -> bool:
        """Re-authenticate if session has expired."""
        if not self.has_credentials:
            return False
        if not self._authed or (time.monotonic() - self._session_ts) > SESSION_TTL:
            return await self._authenticate(session)
        return self._authed

    def _auth_headers(self) -> dict:
        if self._access_jwt:
            return {"Authorization": f"Bearer {self._access_jwt}"}
        return {}

    async def _fetch_author_feed(
        self,
        session: aiohttp.ClientSession,
        account: dict,
    ) -> list[dict]:
        """Fetch recent posts from a single account (no auth required)."""
        handle = account["handle"]
        params = {"actor": handle, "limit": 25}
        cursor = self._cursors.get(handle)
        if cursor:
            params["cursor"] = cursor

        try:
            async with session.get(
                f"{BSKY_PUBLIC}/app.bsky.feed.getAuthorFeed",
                params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers={"Accept": "application/json"},
            ) as resp:
                if resp.status != 200:
                    logger.debug("BlueSky feed %s: HTTP %s", handle, resp.status)
                    return []
                data = await resp.json()
                # Store cursor for next incremental fetch
                if data.get("cursor"):
                    self._cursors[handle] = data["cursor"]
                return [
                    self._post_to_raw(item["post"], account)
                    for item in data.get("feed", [])
                    if "post" in item
                ]
        except Exception as exc:
            logger.debug("BlueSky feed error for %s: %s", handle, exc)
            return []

    async def _search_posts(
        self,
        session: aiohttp.ClientSession,
        query: str,
    ) -> list[dict]:
        """Keyword search — requires auth."""
        if not self._authed:
            return []
        try:
            async with session.get(
                f"{BSKY_API}/app.bsky.feed.searchPosts",
                params={"q": query, "limit": 15, "sort": "latest"},
                headers={"Accept": "application/json", **self._auth_headers()},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    if resp.status == 401:
                        self._authed = False
                    return []
                data = await resp.json()
                synthetic_account = {
                    "handle": f"search:{query}",
                    "category": "search",
                    "reliability": 0.75,
                }
                return [
                    self._post_to_raw(post, synthetic_account)
                    for post in data.get("posts", [])
                ]
        except Exception as exc:
            logger.debug("BlueSky search error '%s': %s", query, exc)
            return []

    def _post_to_raw(self, post: dict, account: dict) -> dict:
        """Normalize a BlueSky post dict to a common intermediate format."""
        record = post.get("record", {})
        author = post.get("author", {})
        return {
            "uri": post.get("uri", ""),
            "text": record.get("text", ""),
            "created_at": record.get("createdAt", datetime.now(timezone.utc).isoformat()),
            "handle": author.get("handle", account["handle"]),
            "display_name": author.get("displayName", ""),
            "category": account["category"],
            "reliability": account["reliability"],
            "url": self._uri_to_url(post.get("uri", ""), author.get("handle", "")),
        }

    @staticmethod
    def _uri_to_url(uri: str, handle: str) -> str:
        """Convert AT URI to a bsky.app web URL."""
        # at://did:plc:xxx/app.bsky.feed.post/rkey -> https://bsky.app/profile/handle/post/rkey
        try:
            rkey = uri.rsplit("/", 1)[-1]
            return f"https://bsky.app/profile/{handle}/post/{rkey}"
        except Exception:
            return f"https://bsky.app/profile/{handle}"

    async def collect(self) -> list[dict]:
        """
        Collect from all monitored accounts + keyword searches.
        Returns list of raw post dicts, deduped by URI.
        """
        connector = aiohttp.TCPConnector(limit=20, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Authenticate if credentials are available
            await self._ensure_auth(session)

            # Account feeds (always, no auth required)
            feed_tasks = [
                self._fetch_author_feed(session, acct)
                for acct in MONITORED_ACCOUNTS
            ]
            # Keyword searches (only if authed)
            search_tasks = []
            if self._authed:
                search_tasks = [
                    self._search_posts(session, q)
                    for q in SEARCH_QUERIES
                ]

            all_results = await asyncio.gather(
                *feed_tasks, *search_tasks, return_exceptions=True
            )

        raw_posts: list[dict] = []
        for result in all_results:
            if isinstance(result, list):
                for post in result:
                    uri = post.get("uri", "")
                    if uri and uri not in self._seen_uris:
                        self._seen_uris.add(uri)
                        raw_posts.append(post)

        # Trim seen set to avoid unbounded growth
        if len(self._seen_uris) > 50_000:
            self._seen_uris = set(list(self._seen_uris)[-25_000:])

        logger.info(
            "BlueSky collected %d new posts (auth=%s, accounts=%d, searches=%d)",
            len(raw_posts), self._authed, len(MONITORED_ACCOUNTS),
            len(SEARCH_QUERIES) if self._authed else 0,
        )
        return raw_posts


# Singleton
collector = BlueSkyCollector()
