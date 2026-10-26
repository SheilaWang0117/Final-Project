"""Turn synthetic fixtures into the same structures live agents produce."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..agents.schemas import EventAssessment, IntelligenceReport, Passage, RegulatoryAssessment, RegulatoryReport
from ..db import jdump, utc_now
from ..research.connectors.base import content_hash

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research.json"


def load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _item(f: dict) -> dict:
    return {"connector": "fixture", "source_name": f["source_name"], "kind": "news", "title": f["title"], "url": f["url"], "published_at": f.get("published_at"),
            "excerpt": f.get("excerpt", ""), "retrieved_at": utc_now(), "content_hash": content_hash(f["title"], f.get("excerpt")), "meta": {}, "language": "en"}


def fixture_report(key: str, program: dict) -> tuple[dict, IntelligenceReport]:
    data = load()[key]
    cands, assessments = {}, []
    species = set(program.get("species") or [])
    for f in data:
        cands[f["id"]] = _item(f)
        a = f.get("assessment")
        if not a:
            continue  # e.g. the injection fixture: never turned into an event
        if not species & set(f.get("species", [])):
            continue
        assessments.append(EventAssessment(item_id=f["id"], relevant=True, **a))
    return cands, IntelligenceReport(assessments=assessments, injection_detected=True, coverage_note="Demo fixtures only.")


def fixture_briefing(today: date) -> list[dict]:
    out = []
    for f in load()["briefing"]:
        sc = round(0.45 * f["significance"] + 0.35 * f["pipeline_relevance"] + 0.10 * 100 + 0.10 * f["authority"], 1)
        out.append({"section": f["section"], "title": f["title"], "summary": f["summary"], "why_it_matters": f["why_it_matters"], "source": f["source"], "url": f["url"],
                    "published_at": today.isoformat(), "retrieved_at": utc_now(), "score": {"total": sc, "significance": f["significance"], "pipeline_relevance": f["pipeline_relevance"], "recency": 100, "authority": f["authority"]},
                    "fixture": True})
    out.sort(key=lambda s: -s["score"]["total"])
    if out:
        out[0]["lead"] = True
    return out


def fixture_regulatory(program: dict, milestone_ids: list[int]) -> tuple[dict, RegulatoryReport]:
    from ..db import connect

    data = load()["regulatory"]
    cands, assessments = {}, []
    conn = connect()
    try:
        names = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM milestones WHERE program_id = ?", (program["id"],))}
    finally:
        conn.close()
    for f in data:
        if f["jurisdiction"] not in (program.get("jurisdictions") or []):
            continue
        it = _item({**f, "source_name": f["authority"], "excerpt": f["text"]})
        it.update({"connector": "fixture_regulatory", "language": f["language"], "original_title": f.get("original_title"),
                   "meta": {"jurisdiction": f["jurisdiction"], "doc_status": f["doc_status"], "binding": f["binding"]}})
        cands[f["id"]] = it
        a = dict(f["assessment"])
        ms = a.pop("affected_milestone", None)
        a["passages"] = [Passage(**p) for p in a["passages"]]
        assessments.append(RegulatoryAssessment(doc_id=f["id"], affected_milestone_ids=[names[ms]] if ms in names else [], **a))
    return cands, RegulatoryReport(assessments=assessments)


def fixture_market(conn) -> int:
    n = 0
    for f in load()["market"]:
        conn.execute(
            "INSERT OR IGNORE INTO market_observations (market_definition, species, geography, product_category, period, metric, company, segment, value, unit, currency, value_type, source_name, source_url, retrieved_at, coverage_note, origin) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'sample', ?, ?, ?, ?, 'fixture')",
            ("SAMPLE DATA: illustrative company revenue", "all animals", "Global (sample)", "Animal health", f["period"], "revenue", f["company"], "total", f["value"], f["unit"], "USD",
             "Synthetic sample", "https://example.org/fixture/market", utc_now(), "Sample values for the demo; not real companies."))
        n += 1
    return n


def fixture_partners(conn, program_id: int) -> int:
    from ..agents.market import WEIGHTS

    n = 0
    for f in load()["partners"]:
        ev = [{**e, "retrieved_at": utc_now(), "date": None} for e in f["evidence"]]
        # same rule as live mode: a criterion counts only if a cited source supports it
        criteria = {c: int(any(e["criterion"] == c for e in ev)) for c in WEIGHTS}
        score = sum(WEIGHTS[c] for c, v in criteria.items() if v)
        f = {**f, "criteria": criteria}
        conn.execute(
            "INSERT INTO partner_candidates (program_id, company, evidence_json, criteria_json, fit_score, ai_assessment, gaps_json, origin, updated_at) VALUES (?,?,?,?,?,?,?, 'fixture', ?) "
            "ON CONFLICT(program_id, company) DO UPDATE SET evidence_json=excluded.evidence_json, criteria_json=excluded.criteria_json, fit_score=excluded.fit_score, ai_assessment=excluded.ai_assessment, updated_at=excluded.updated_at",
            (program_id, f["company"], jdump(ev), jdump(f["criteria"]), score, f["assessment"], jdump(f["gaps"]), utc_now()))
        n += 1
    return n
