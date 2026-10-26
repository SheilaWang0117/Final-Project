"""Keep confidential internal data out of public queries and model context.

Public search terms are built only from the confirmed, non-confidential
profile fields (species, indication, modality, target/mechanism class,
molecule category, therapeutic area, and user-approved public keywords).
Program codes, names, descriptions, notes, risks, budgets and transactions are
never used. Every outbound query is checked again before it is sent.
"""

from __future__ import annotations

import re
import sqlite3

from ..db import get_setting, jload

PUBLIC_PROFILE_FIELDS = ("species", "indication", "modality", "target", "mechanism", "molecule_category", "therapeutic_area", "public_keywords")

_AMOUNT_RE = re.compile(r"(?:\b(?:usd|hkd|cny|rmb)\s?\$?\s?\d|[$¥]\s?\d|\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b)", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class ConfidentialQuery(ValueError):
    pass


def confidential_terms(conn: sqlite3.Connection) -> list[str]:
    """Program codes plus any user-listed confidential terms (Settings)."""
    terms = [r[0] for r in conn.execute("SELECT code FROM programs")]
    extra = get_setting(conn, "confidential_terms", "") or ""
    terms += [t.strip() for t in extra.split(",") if t.strip()]
    company = get_setting(conn, "company_name", "") or ""
    if company:
        terms.append(company)
    return [t for t in terms if len(t) >= 3]


def check_public_query(query: str, conn: sqlite3.Connection) -> str:
    q = " ".join((query or "").split())
    if not q:
        raise ConfidentialQuery("empty query")
    if len(q) > 200:
        raise ConfidentialQuery("query too long for a public search")
    low = q.lower()
    for term in confidential_terms(conn):
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", low):
            raise ConfidentialQuery(f"query contains a confidential internal term")
    if _AMOUNT_RE.search(q):
        raise ConfidentialQuery("query contains a monetary amount or long number")
    if _EMAIL_RE.search(q):
        raise ConfidentialQuery("query contains an email address")
    return q


def public_profile(program: dict) -> dict:
    """The only program fields that may leave the application for research."""
    out = {}
    for f in PUBLIC_PROFILE_FIELDS:
        v = program.get(f)
        if v in (None, "", [], "unknown"):
            continue
        out[f] = v
    if program.get("use_type") in ("human", "veterinary"):
        out["use_type"] = program["use_type"]
    out["jurisdictions"] = program.get("jurisdictions") or []
    return out


SPECIES_TERMS = {
    "dog": ["canine", "dog"], "dogs": ["canine", "dog"], "canine": ["canine", "dog"],
    "cat": ["feline", "cat"], "cats": ["feline", "cat"], "feline": ["feline", "cat"],
    "horse": ["equine", "horse"], "equine": ["equine", "horse"],
}


def species_terms(species: list[str]) -> list[str]:
    out: list[str] = []
    for s in species or []:
        for t in SPECIES_TERMS.get(s.lower().strip(), [s.lower().strip()]):
            if t not in out:
                out.append(t)
    return out


def build_queries(program: dict, conn: sqlite3.Connection, max_queries: int = 4) -> list[str]:
    """Generic public queries from the confirmed profile. Each is guard-checked."""
    p = public_profile(program)
    sp = species_terms(p.get("species", []))
    sp_main = sp[0] if sp else ""

    def clean(v):
        return re.sub(r"\s*\([^)]*\)", "", (v or "")).strip()

    ind, mod, target = clean(p.get("indication")), clean(p.get("modality")), clean(p.get("target"))
    cands = []
    if sp_main and ind:
        cands.append(f"{sp_main} {ind}")
    if sp_main and mod:
        cands.append(f"{sp_main} {mod}")
    if sp_main and target:
        cands.append(f"{sp_main} {target}")
    if not sp_main and ind and mod:
        cands.append(f"{ind} {mod}")
    for kw in p.get("public_keywords", [])[:3]:
        kw = clean(kw)
        has_species = any(t in kw.lower() for t in SPECIES_TERMS)
        cands.append(kw if has_species else f"{sp_main} {kw}".strip())
    if sp_main and not cands:
        cands.append(f"{sp_main} oncology")
    out = []
    for c in cands:
        try:
            q = check_public_query(c, conn)
        except ConfidentialQuery:
            continue
        if q.lower() not in [x.lower() for x in out]:
            out.append(q)
    return out[:max_queries]


def program_from_row(r) -> dict:
    d = dict(r)
    d["species"] = jload(d.get("species_json"), [])
    d["jurisdictions"] = jload(d.get("jurisdictions_json"), [])
    d["public_keywords"] = jload(d.get("public_keywords_json"), [])
    return d
