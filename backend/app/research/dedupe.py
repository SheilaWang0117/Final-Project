"""URL canonicalization and near-duplicate detection for retrieved items."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|cmp$|src$)", re.I)


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunsplit(("https", host, path, query, ""))


def url_key(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:24]


def title_tokens(title: str) -> set[str]:
    stop = {"the", "a", "an", "of", "for", "and", "in", "to", "on", "with", "by", "at", "as", "its", "is"}
    return {t for t in re.findall(r"[a-z0-9一-鿿가-힯぀-ヿ]+", (title or "").lower()) if t not in stop and len(t) > 1}


def similar_titles(a: str, b: str, threshold: float = 0.75) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def dedupe_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (unique, duplicates). Keeps the first (most primary) occurrence."""
    unique: list[dict] = []
    dups: list[dict] = []
    seen_urls: set[str] = set()
    for it in items:
        cu = canonical_url(it["url"])
        if cu in seen_urls:
            dups.append({**it, "duplicate_reason": "same URL"})
            continue
        twin = next((u for u in unique if similar_titles(u["title"], it["title"])), None)
        if twin:
            dups.append({**it, "duplicate_reason": f"same story as '{twin['title'][:60]}'"})
            continue
        seen_urls.add(cu)
        unique.append(it)
    return unique, dups
