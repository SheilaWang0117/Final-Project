"""Shared public-research cache (separate SQLite file).

Only publicly retrieved content lives here, keyed by URL, so it can be reused
across users without exposing internal records. Internal data (programs,
budgets, notes) is never written to this database.

This is the *application* retrieval cache. It is unrelated to provider-side
prompt caching, which the model provider reports as cached input tokens.
"""

from __future__ import annotations

import sqlite3
import zlib
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from .http import FetchResult, fetch

_SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    final_url TEXT NOT NULL,
    status INTEGER NOT NULL,
    content_type TEXT,
    sha256 TEXT NOT NULL,
    body BLOB NOT NULL,
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS content_versions (
    url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (url, sha256)
);
"""


class CacheStats:
    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.errors: list[dict] = []
        self.sources: list[dict] = []

    def as_dict(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "errors": self.errors[:20]}


def _conn() -> sqlite3.Connection:
    path = get_settings().research_cache_path
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def cached_fetch(url: str, *, ttl_hours: float | None = None, stats: CacheStats | None = None, use_cache: bool = True, **kw) -> FetchResult:
    ttl = get_settings().research_cache_ttl_hours if ttl_hours is None else ttl_hours
    if use_cache:
        with _conn() as c:
            r = c.execute("SELECT * FROM http_cache WHERE url = ?", (url,)).fetchone()
            if r and r["expires_at"] > _now().isoformat():
                c.execute("UPDATE http_cache SET hits = hits + 1 WHERE url = ?", (url,))
                if stats:
                    stats.hits += 1
                return FetchResult(url, r["final_url"], r["status"], r["content_type"] or "", zlib.decompress(r["body"]), r["retrieved_at"], r["sha256"], from_cache=True)
    if stats:
        stats.misses += 1
    res = await fetch(url, **kw)
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO http_cache (url, final_url, status, content_type, sha256, body, retrieved_at, expires_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET final_url=excluded.final_url, status=excluded.status, content_type=excluded.content_type, sha256=excluded.sha256, "
            "body=excluded.body, retrieved_at=excluded.retrieved_at, expires_at=excluded.expires_at",
            (url, res.final_url, res.status, res.content_type, res.sha256, zlib.compress(res.body), res.retrieved_at, (now + timedelta(hours=ttl)).isoformat()),
        )
        c.execute(
            "INSERT INTO content_versions (url, sha256, first_seen, last_seen) VALUES (?,?,?,?) ON CONFLICT(url, sha256) DO UPDATE SET last_seen = excluded.last_seen",
            (url, res.sha256, res.retrieved_at, res.retrieved_at),
        )
    return res


def versions(url: str) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM content_versions WHERE url = ? ORDER BY first_seen", (url,))]


def stats_summary() -> dict:
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(hits),0) AS hits, COALESCE(SUM(LENGTH(body)),0) AS bytes, MAX(retrieved_at) AS latest FROM http_cache").fetchone()
        return dict(r)


def clear_expired() -> int:
    with _conn() as c:
        return c.execute("DELETE FROM http_cache WHERE expires_at < ?", (_now().isoformat(),)).rowcount
