"""Market and Partner Agent.

Market observations: reported annual revenue from SEC XBRL filings for
US-listed animal-health companies (deterministic; no AI). These are company
revenues, NOT market shares; the UI shows them as a comparable-revenue chart
with definitions and gaps.

Partner candidates: public evidence is gathered per company (SEC full-text
filings, Europe PMC affiliation search, captured competitor events, and
user-supplied public URLs). The agent maps evidence ids to criteria and
writes a labeled assessment. The fit score is computed by code from which
criteria have documented evidence.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from ..config import get_settings
from ..db import connect, jdump, jload, log_activity, utc_now
from ..research.connectors import sources as S
from ..research.guard import program_from_row, public_profile, species_terms
from .common import Deps, make_agent, mode
from .intelligence import _gather
from .runner import AgentFailure, Recorder, finish_ok, record_demo_run, run_agent, untrusted_block
from .schemas import PartnerReport

CRITERIA = ["therapeutic_species_fit", "portfolio_relevance", "geographic_capability", "commercial_capability", "prior_licensing_activity", "stated_strategic_interest"]
WEIGHTS = {"therapeutic_species_fit": 25, "portfolio_relevance": 20, "geographic_capability": 15, "commercial_capability": 15, "prior_licensing_activity": 15, "stated_strategic_interest": 10}

# Starting set of animal-health companies with public evidence channels. Being on
# this list means "worth checking", not interest. Users can add companies.
PARTNER_UNIVERSE = {
    "Zoetis": {"cik": "0001555280", "aff": "Zoetis"},
    "Elanco Animal Health": {"cik": "0001739104", "aff": "Elanco"},
    "Merck Animal Health (Merck & Co.)": {"cik": "0000310158", "aff": "Merck Animal Health"},
    "Boehringer Ingelheim Animal Health": {"cik": None, "aff": "Boehringer Ingelheim"},
    "Virbac": {"cik": None, "aff": "Virbac"},
    "Vetoquinol": {"cik": None, "aff": "Vetoquinol"},
    "Ceva Santé Animale": {"cik": None, "aff": "Ceva"},
    "Dechra Pharmaceuticals": {"cik": None, "aff": "Dechra"},
}


async def refresh_market(*, job_id: int | None = None) -> dict:
    """Store reported revenue observations (no model call)."""
    conn = connect()
    try:
        rec = Recorder("market_data", mode(), job_id=job_id).start(conn)
        if rec.mode == "demo":
            from ..demo.fixtures_loader import fixture_market

            n = fixture_market(conn)
            conn.commit()
            run = record_demo_run("market_data", rec, "Sample (synthetic) market observations; clearly labeled 'sample'.")
            return {"stored": n, "run": run, "mode": "demo"}
        tasks = {name: S.sec_annual_revenue(cik, stats=rec.cache) for name, (cik, _note) in S.ANIMAL_HEALTH_COMPANIES.items()}
        names = list(tasks)
        import asyncio

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        stored = 0
        coverage = {}
        for name, res in zip(names, results):
            if isinstance(res, Exception):
                coverage[name] = {"ok": False, "error": f"{type(res).__name__}"}
                rec.step(f"retrieve:sec:{name}", ok=False, error=str(res)[:200])
                continue
            coverage[name] = {"ok": True, "years": len(res)}
            rec.step(f"retrieve:sec:{name}", {"facts": len(res)})
            note = S.ANIMAL_HEALTH_COMPANIES[name][1]
            for f in res[-6:]:
                conn.execute(
                    "INSERT INTO market_observations (market_definition, species, geography, product_category, period, metric, company, segment, value, unit, currency, value_type, "
                    "source_name, source_url, retrieved_at, coverage_note, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(market_definition, period, metric, company, segment, source_url) DO UPDATE SET value=excluded.value, retrieved_at=excluded.retrieved_at",
                    ("Company-reported total revenue (animal-health companies)", "all animals", "Global (company-reported)", "Animal health",
                     f"FY ending {f['end']}", "revenue", name, "total", str(f["value"]), "USD", "USD", "reported",
                     f"SEC EDGAR XBRL ({f['concept']}, 10-K filed {f['filed']})", f["source_url"], f["retrieved_at"],
                     f"{note} Fiscal periods differ by company. Revenue covers all species and products, not a specific indication.", "agent"))
                stored += 1
            rec.source(f"{name} 10-K revenue (SEC XBRL)", res[-1]["source_url"] if res else "", res[-1]["retrieved_at"] if res else None)
        log_activity(conn, "market_refresh", "market_observations", None, {"stored": stored}, actor="Market and Partner Agent")
        conn.commit()
        run = finish_ok(rec)
        return {"stored": stored, "coverage": coverage, "run": run}
    finally:
        conn.close()


async def _filing_sentences(url: str, terms: list[str], rec: Recorder, max_sentences: int = 4) -> str:
    """Extract sentences from a public filing that mention the species AND a relevant term (deterministic)."""
    import re

    from bs4 import BeautifulSoup

    from ..research.cache import cached_fetch

    try:
        res = await cached_fetch(url, stats=rec.cache, ttl_hours=168, max_bytes=12 * 1024 * 1024, headers={"User-Agent": get_settings().sec_user_agent})
    except Exception as exc:  # noqa: BLE001
        rec.step("filing_text", {"url": url[-60:]}, ok=False, error=str(exc)[:120])
        return ""
    text = BeautifulSoup(res.body, "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text)
    species = [t for t in terms[:2]]
    others = [t for t in terms[2:]]
    out = []
    for sent in re.split(r"(?<=[.;])\s+", text):
        low = sent.lower()
        if 40 <= len(sent) <= 500 and any(s in low for s in species) and any(o in low for o in others):
            out.append(sent.strip())
            if len(out) >= max_sentences:
                break
    return " | ".join(out)[:900]


async def _company_evidence(name: str, info: dict, program: dict, rec: Recorder, conn) -> list[dict]:
    sp = species_terms(public_profile(program).get("species", []))
    sp_q = " OR ".join(sp[:2]) or "animal"
    since = date.today() - timedelta(days=3 * 365)
    tasks = {}
    if info.get("cik"):
        tasks[f"sec:{name}:species"] = S.sec_full_text(f'"{sp[0] if sp else "companion animal"}" "monoclonal"', stats=rec.cache, cik=info["cik"], limit=3, since=since)
        tasks[f"sec:{name}:licensing"] = S.sec_full_text('"license agreement" "animal health"', stats=rec.cache, cik=info["cik"], limit=3, since=since)
    if info.get("aff"):
        tasks[f"europepmc:{name}"] = S.search_europepmc(f'AFF:"{info["aff"]}" AND ({sp_q}) AND (cancer OR tumor OR tumour OR oncology OR antibody OR immunotherapy)', stats=rec.cache, limit=4, since=since, raw=True)
    items, cov = await _gather(rec, tasks)
    ev = []
    sec_seen = 0
    for it in items:
        crit_hint = "prior_licensing_activity" if ":licensing" in it["connector"] else "therapeutic_species_fit"
        excerpt = it["excerpt"][:300]
        if it["source_name"] == "SEC EDGAR":
            if not get_settings().sec_contact_configured:
                # SEC's fair-access policy requires a contact in the User-Agent for www.sec.gov documents.
                if not rec.tool_counts.get("sec_notice"):
                    rec.tool_counts["sec_notice"] = 1
                    rec.step("filing_text", {"note": "Skipped: set SEC_USER_AGENT='Company Name contact@example.com' to read filing text (SEC fair-access policy)."}, ok=False, error="SEC_USER_AGENT not configured")
                continue
            if sec_seen >= 3:
                continue
            sec_seen += 1
            snippet = await _filing_sentences(it["url"], sp + ["monoclonal", "antibod", "oncolog", "cancer", "licens", "china", "asia"], rec)
            if not snippet:
                continue  # a filing without matching sentences is not evidence
            excerpt = snippet
        ev.append({"source_name": it["source_name"], "title": it["title"], "url": it["url"], "date": it["published_at"], "excerpt": excerpt, "retrieved_at": it["retrieved_at"], "hint": crit_hint})
    for r in conn.execute("SELECT title, source_url, source_name, published_at, retrieved_at FROM intel_events WHERE program_id = ? AND (lower(title) LIKE ? OR lower(observed) LIKE ?) LIMIT 3",
                          (program["id"], f"%{info.get('aff', name).lower()}%", f"%{info.get('aff', name).lower()}%")):
        ev.append({"source_name": r["source_name"], "title": r["title"], "url": r["source_url"], "date": r["published_at"], "excerpt": "", "retrieved_at": r["retrieved_at"], "hint": "portfolio_relevance"})
    for r in conn.execute("SELECT evidence_json FROM partner_candidates WHERE program_id = ? AND company = ?", (program["id"], name)):
        for e in jload(r["evidence_json"], []):
            if e.get("user_supplied"):
                ev.append({"source_name": e.get("source_name", "User-supplied URL"), "title": e.get("fact", ""), "url": e["source_url"], "date": None, "excerpt": e.get("excerpt", ""), "retrieved_at": e.get("retrieved_at"), "hint": e.get("criterion"), "user_supplied": True})
    return ev


async def refresh_partners(program_id: int, *, job_id: int | None = None, model=None) -> dict:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone()
        if not r:
            raise AgentFailure("Program not found")
        program = program_from_row(r)
        if not program.get("profile_confirmed_at"):
            raise AgentFailure("Confirm the program profile before partner research.")
        rec = Recorder("market_partner", mode() if model is None else "test", job_id=job_id).start(conn)
        if rec.mode == "demo":
            from ..demo.fixtures_loader import fixture_partners

            n = fixture_partners(conn, program_id)
            conn.commit()
            run = record_demo_run("market_partner", rec, "Demo fixtures; synthetic evidence clearly labeled.")
            return {"partners": n, "run": run, "mode": "demo"}
        universe = dict(PARTNER_UNIVERSE)
        for c in conn.execute("SELECT DISTINCT company FROM partner_candidates WHERE program_id = ?", (program_id,)):
            universe.setdefault(c["company"], {"cik": None, "aff": c["company"]})
        evidence: dict[str, dict] = {}
        per_company: dict[str, list[str]] = {}
        for name, info in universe.items():
            ev = await _company_evidence(name, info, program, rec, conn)
            ids = []
            for e in ev:
                eid = f"e{len(evidence) + 1}"
                evidence[eid] = {**e, "company": name}
                ids.append(eid)
            per_company[name] = ids
        from ..research.injection import instruction_like

        for eid in [e for e, v in evidence.items() if instruction_like(f"{v['title']} {v['excerpt']}")]:
            rec.quarantined += 1
            rec.step("quarantine", {"item": evidence[eid]["url"][:120]}, ok=False, error="instruction-like retrieved text withheld from the model")
            evidence.pop(eid)
            for ids in per_company.values():
                if eid in ids:
                    ids.remove(eid)
        blocks = []
        for name, ids in per_company.items():
            body = "\n".join(f"[{i}] {evidence[i]['source_name']} | {evidence[i]['date'] or 'n/a'} | {evidence[i]['title'][:160]} | {evidence[i]['excerpt'][:200]}" for i in ids) or "(no evidence found)"
            blocks.append(untrusted_block(f"company:{name}", f"Company: {name}\n{body}"))
        agent = make_agent("market", PartnerReport, model=model)
        prompt = f"Program public profile: {json.dumps(public_profile(program))}\n\nEvidence by company:\n" + "\n".join(blocks)
        report = await run_agent(agent, prompt, deps=Deps(rec=rec, program_id=program_id, candidates=evidence), rec=rec)
        now = utc_now()
        stored = 0
        for p in report.partners:
            if p.company not in universe:
                continue
            crit: dict[str, int] = {c: 0 for c in CRITERIA}
            ev_out = []
            for ce in p.criteria:
                valid = [i for i in ce.evidence_ids if i in evidence and evidence[i]["company"] == p.company]
                if valid:
                    crit[ce.criterion] = 1
                for i in valid:
                    e = evidence[i]
                    if any(x["criterion"] == ce.criterion and x["source_url"] == e["url"] for x in ev_out):
                        continue
                    ev_out.append({"criterion": ce.criterion, "fact": e["title"], "source_name": e["source_name"], "source_url": e["url"], "date": e["date"], "retrieved_at": e["retrieved_at"], "user_supplied": e.get("user_supplied", False)})
            score = sum(WEIGHTS[c] for c, v in crit.items() if v)
            conn.execute(
                "INSERT INTO partner_candidates (program_id, company, evidence_json, criteria_json, fit_score, ai_assessment, gaps_json, agent_run_id, origin, updated_at) VALUES (?,?,?,?,?,?,?,?, 'agent', ?) "
                "ON CONFLICT(program_id, company) DO UPDATE SET evidence_json=excluded.evidence_json, criteria_json=excluded.criteria_json, fit_score=excluded.fit_score, ai_assessment=excluded.ai_assessment, gaps_json=excluded.gaps_json, agent_run_id=excluded.agent_run_id, updated_at=excluded.updated_at",
                (program_id, p.company, jdump(ev_out), jdump(crit), score, p.assessment, jdump(p.gaps), rec.run_id, now))
            stored += 1
            for e in ev_out[:3]:
                rec.source(e["fact"], e["source_url"], e["retrieved_at"])
        log_activity(conn, "partner_refresh", "partner_candidates", program_id, {"stored": stored}, actor="Market and Partner Agent")
        conn.commit()
        run = finish_ok(rec)
        return {"partners": stored, "evidence_items": len(evidence), "run": run}
    finally:
        conn.close()


SCORING_RULE = "Fit score = sum of criterion weights for criteria with at least one cited public source: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in WEIGHTS.items()) + ". It measures documented evidence, not likelihood of a deal."
