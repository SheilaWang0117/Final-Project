"""Shared helpers for public-source connectors.

Every connector returns plain dict "items" with provenance:
{connector, source_name, kind, title, original_title, language, url,
 published_at, updated_at, excerpt, meta, retrieved_at, content_hash, from_cache}
Retrieved text is untrusted: it is stored and shown as data, and only passed
to models inside clearly delimited untrusted-content blocks.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..cache import CacheStats

MAX_EXCERPT = 1500


def clean_text(value: str | None, limit: int = MAX_EXCERPT) -> str:
    if not value:
        return ""
    text = BeautifulSoup(value, "html.parser").get_text(" ") if "<" in value else value
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def content_hash(*parts: str | None) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:32]


def iso_date(value) -> str | None:
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    s = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # US format used by FDA
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def item(connector: str, source_name: str, kind: str, title: str, url: str, *, published_at=None, updated_at=None,
         excerpt: str = "", language: str = "en", original_title: str | None = None, meta: dict | None = None,
         retrieved_at: str = "", from_cache: bool = False) -> dict:
    title = clean_text(title, 400)
    excerpt = clean_text(excerpt)
    return {
        "connector": connector, "source_name": source_name, "kind": kind, "title": title,
        "original_title": original_title, "language": language, "url": url,
        "published_at": iso_date(published_at), "updated_at": iso_date(updated_at),
        "excerpt": excerpt, "meta": meta or {}, "retrieved_at": retrieved_at,
        "content_hash": content_hash(title, excerpt, iso_date(updated_at) or iso_date(published_at)),
        "from_cache": from_cache,
    }


def matches(text: str, terms: list[str], mode: str = "all") -> bool:
    low = (text or "").lower()
    hits = [t for t in terms if t and t.lower() in low]
    return len(hits) == len([t for t in terms if t]) if mode == "all" else bool(hits)


__all__ = ["CacheStats", "clean_text", "content_hash", "iso_date", "item", "matches"]
