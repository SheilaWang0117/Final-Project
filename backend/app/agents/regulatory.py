"""Regulatory Research Agent.

1. Pick responsible authorities for the confirmed profile (registry).
2. Retrieve candidate official documents from those sources.
3. The agent judges applicability and may read up to 4 documents; quoted
   passages are kept only if they appear verbatim in the text it read.
4. Status (draft/final) and binding/guidance are set from source metadata,
   not by the model. Changed documents are flagged for human review against
   milestones; the plan itself is never modified.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic_ai import RunContext

from ..db import connect, jdump, log_activity, utc_now
from ..research.connectors import sources as S
from ..research.guard import program_from_row, public_profile
from ..research.injection import quarantine, scrub
from ..research.registry import JURISDICTIONS, scopes_for, seed
from .common import Deps, is_verbatim, make_agent, mode
from .intelligence import _gather
from .runner import AgentFailure, Recorder, finish_ok, record_demo_run, run_agent, traced, untrusted_block
from .schemas import RegulatoryReport

VET_TERMS = ["monoclonal", "antibod", "biolog", "biotechnolog", "oncolog", "cancer", "companion", "conditional", "target animal safety", "effectiveness",
             "chemistry, manufacturing", "cmc", "recombinant", "investigational", "field stud", "dog", "canine", "feline", "cat"]
HUMAN_TERMS = ["monoclonal", "antibod", "bispecific", "oncolog", "cancer", "biolog", "accelerated", "breakthrough", "first-in-human", "nonclinical", "cmc", "chemistry, manufacturing"]


def _terms(program: dict, vet: bool) -> list[str]:
    base = VET_TERMS if vet else HUMAN_TERMS
    extra = []
    mod = (program.get("modality") or "").lower()
    if "bispecific" in mod:
        extra.append("bispecific")
    if "gene" in mod or "plasmid" in mod:
        extra += ["gene therap", "plasmid"]
    if "small" in mod or program.get("molecule_category") == "small_molecule":
        base = [t for t in base if t not in ("monoclonal", "antibod", "biolog", "recombinant")]
    return list(dict.fromkeys(base + extra))


async def regulatory_candidates(program: dict, conn, rec: Recorder) -> tuple[list[dict], dict, dict]:
    jur = [j for j in (program.get("jurisdictions") or []) if j in JURISDICTIONS] or JURISDICTIONS
    scopes = scopes_for(program)
    vet = any(s.startswith("vet") for s in scopes)
    human = any(s.startswith("human") for s in scopes)
    tasks, plan = {}, {}
    if "US" in jur:
        if vet:
            tasks["fda_guidance:CVM"] = S.search_fda_guidance(_terms(program, True), stats=rec.cache, centers=["Veterinary"], limit=20)
            tasks["federal_register:vet"] = S.search_federal_register("veterinary biologics OR new animal drug", stats=rec.cache, limit=6, since=date.today() - timedelta(days=365))
        if human:
            tasks["fda_guidance:CDER/CBER"] = S.search_fda_guidance(_terms(program, False), stats=rec.cache, centers=["Drug Evaluation", "Biologics Evaluation"], limit=10)
    if "EU" in jur:
        if vet:
            tasks["ema:veterinary"] = S.search_ema_documents(_terms(program, True), stats=rec.cache, veterinary=True, limit=15)
        if human:
            tasks["ema:human"] = S.search_ema_documents(_terms(program, False), stats=rec.cache, veterinary=False, limit=10)
    if "CN" in jur and vet:
        tasks["index:mara_notices"] = S.scan_index_page("mara_notices", stats=rec.cache)
    if "JP" in jur:
        if vet:
            tasks["index:nval"] = S.scan_index_page("nval", stats=rec.cache)
        if human:
            tasks["index:pmda"] = S.scan_index_page("pmda", stats=rec.cache)
    if "KR" in jur:
        if vet:
            tasks["index:apqa"] = S.scan_index_page("apqa", stats=rec.cache)
        if human:
            tasks["index:mfds_guideline"] = S.scan_index_page("mfds_guideline", stats=rec.cache)
    plan = {"jurisdictions": jur, "scopes": scopes, "not_searched": [j for j in JURISDICTIONS if j not in jur],
            "manual_only": [dict(r) for r in conn.execute("SELECT jurisdiction, authority, url, notes FROM regulatory_sources WHERE access = 'manual_only' AND jurisdiction IN (%s)" % ",".join("?" * len(jur)), jur)]}
    rec.step("search_plan", plan)
    items, coverage = await _gather(rec, tasks)
    _update_source_status(conn, coverage)
    return items, coverage, plan


def _update_source_status(conn, coverage: dict):
    mapping = {"fda_guidance": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents", "federal_register": "https://www.federalregister.gov/api/v1",
               "ema": "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json"}
    for name, cov in coverage.items():
        prefix = name.split(":")[0]
        url = mapping.get(prefix)
        if prefix == "index":
            url = S.INDEX_PAGES[name.split(":")[1]][3]
        if not url:
            continue
        now = utc_now()
        if cov["ok"]:
            conn.execute("UPDATE regulatory_sources SET last_checked_at = ?, last_success_at = ?, last_status = 'ok', last_error = NULL WHERE url = ?", (now, now, url))
        else:
            conn.execute("UPDATE regulatory_sources SET last_checked_at = ?, last_status = 'failed', last_error = ? WHERE url = ?", (now, cov["error"][:300], url))
    conn.commit()


def _jur_of(item: dict) -> tuple[str, str]:
    c = item["connector"]
    if c.startswith("fda_guidance"):
        return "US", "FDA " + (item["meta"].get("center") or "")
    if c == "federal_register":
        return "US", item["meta"].get("agencies") or "Federal Register"
    if c == "ema_documents":
        return "EU", "European Medicines Agency"
    if c.startswith("index:") or c.startswith("fixture"):
        return item["meta"].get("jurisdiction", "?"), item["source_name"]
    return "?", item["source_name"]


def _status_binding(item: dict) -> tuple[str, str]:
    m = item["meta"]
    if item["connector"].startswith("fixture"):
        return m.get("doc_status", "unknown"), m.get("binding", "unknown")
    if item["connector"] == "federal_register":
        t = (m.get("type") or "").lower()
        if t == "rule":
            return "final", "binding"
        if "proposed" in t:
            return "draft", "unknown"
        return "unknown", "unknown"
    if item["connector"] in ("fda_guidance", "ema_documents"):
        return m.get("doc_status", "unknown"), "guidance"
    return "unknown", "unknown"


@traced
async def read_document(ctx: RunContext[Deps], doc_id: str) -> dict:
    """Read the text of one listed official document (by doc_id). Untrusted content."""
    it = ctx.deps.candidates.get(doc_id)
    if not it:
        ctx.deps.rec.blocked.append({"tool": "read_document", "requested": doc_id[:80], "reason": "not an approved candidate"})
        return {"error": "Unknown doc_id. Only listed documents can be read."}
    url = it["url"]
    if it["connector"] == "fda_guidance" and it["meta"].get("pdf_url"):
        url = it["meta"]["pdf_url"]
    doc = await S.fetch_document_text(url, stats=ctx.deps.rec.cache, max_chars=9000)
    doc["text"], removed = scrub(doc["text"])
    if removed:
        ctx.deps.rec.step("scrub", {"doc_id": doc_id, "lines_removed": removed}, ok=False, error="instruction-like lines removed from retrieved text")
    ctx.deps.read_texts[doc_id] = doc["text"]
    ctx.deps.extra.setdefault("hashes", {})[doc_id] = doc["sha256"]
    ctx.deps.rec.source(it["title"], it["url"], doc["retrieved_at"], doc["from_cache"])
    return {"doc_id": doc_id, "content": untrusted_block(doc_id, doc["text"]), "truncated": doc["truncated"]}


def store(conn, program_id: int, cands: dict, report: RegulatoryReport, deps: Deps | None, run_id, origin: str, milestone_ids: set[int]) -> dict:
    now = utc_now()
    counts = {"documents_new": 0, "documents_changed": 0, "assessed": 0, "passages_kept": 0, "passages_dropped": 0, "milestone_flags": 0}
    for a in report.assessments:
        it = cands.get(a.doc_id)
        if not it or a.relevance < 30:
            continue
        jur, authority = _jur_of(it)
        status, binding = _status_binding(it)
        chash = (deps.extra.get("hashes", {}).get(a.doc_id) if deps else None) or it["content_hash"]
        existing = conn.execute("SELECT * FROM regulatory_documents WHERE url = ?", (it["url"],)).fetchone()
        changed = False
        if existing:
            doc_id = existing["id"]
            if existing["content_hash"] and existing["content_hash"] != chash:
                changed = True
                conn.execute("UPDATE regulatory_documents SET content_hash=?, previous_hash=?, version=version+1, changed_at=?, retrieved_at=?, doc_status=?, revised_date=? WHERE id=?",
                             (chash, existing["content_hash"], now, it["retrieved_at"] or now, status, it.get("updated_at"), doc_id))
                counts["documents_changed"] += 1
            else:
                conn.execute("UPDATE regulatory_documents SET retrieved_at = ? WHERE id = ?", (it["retrieved_at"] or now, doc_id))
        else:
            doc_id = conn.execute(
                "INSERT INTO regulatory_documents (jurisdiction, authority, title, original_title, language, url, product_scope, species_json, published_date, revised_date, "
                "doc_status, binding, topics_json, retrieved_at, content_hash, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (jur, authority, it["title"], it.get("original_title"), it.get("language", "en"), it["url"], None, "[]", it["published_at"], it.get("updated_at"),
                 status, binding, jdump(list(a.topics)), it["retrieved_at"] or now, chash, origin)).lastrowid
            counts["documents_new"] += 1
        text = deps.read_texts.get(a.doc_id, "") if deps else it.get("excerpt", "")
        passages = []
        for p in a.passages:
            if text and is_verbatim(p.text, text, min_len=20):
                passages.append(p.model_dump())
                counts["passages_kept"] += 1
            else:
                counts["passages_dropped"] += 1
        affected = [m for m in a.affected_milestone_ids if m in milestone_ids]
        review = "needs_review"
        conn.execute(
            "INSERT INTO regulatory_assessments (document_id, program_id, relevance, summary_en, is_translation, passages_json, applicability, unresolved_json, affected_milestones_json, review_status, agent_run_id, origin, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id, program_id) DO UPDATE SET relevance=excluded.relevance, summary_en=excluded.summary_en, is_translation=excluded.is_translation, "
            "passages_json=CASE WHEN excluded.passages_json != '[]' THEN excluded.passages_json ELSE regulatory_assessments.passages_json END, applicability=excluded.applicability, unresolved_json=excluded.unresolved_json, "
            "affected_milestones_json=excluded.affected_milestones_json, review_status=CASE WHEN ? THEN 'needs_review' ELSE regulatory_assessments.review_status END, agent_run_id=excluded.agent_run_id",
            (doc_id, program_id, a.relevance, a.summary_en, int(a.is_translation or it.get("language", "en") != "en"), jdump(passages), a.applicability,
             jdump(a.unresolved_questions), jdump(affected), review, run_id, origin, now, 1 if changed else 0))
        counts["assessed"] += 1
        if affected and (changed or not existing):
            counts["milestone_flags"] += len(affected)
            conn.execute("INSERT INTO actions (title, detail, program_id, source_type, source_id, priority, status, created_by, origin, created_at, updated_at) VALUES (?,?,?,?,?,?, 'proposed', 'agent', ?, ?, ?)",
                         (f"Review regulatory document against milestone(s) {', '.join(map(str, affected))}: {it['title'][:150]}",
                          ("Document changed since last check. " if changed else "") + "Flagged by the Regulatory Research Agent for specialist review; the plan has not been changed.",
                          program_id, "regulatory_document", doc_id, "high" if changed else "medium", origin, now, now))
    return counts


async def refresh_regulatory(program_id: int, *, job_id: int | None = None, model=None) -> dict:
    conn = connect()
    try:
        seed(conn)
        conn.commit()
        r = conn.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone()
        if not r:
            raise AgentFailure("Program not found")
        program = program_from_row(r)
        if not program.get("profile_confirmed_at"):
            raise AgentFailure("Confirm the program profile before regulatory research.")
        milestones = [dict(m) for m in conn.execute("SELECT id, name, stage, planned_end FROM milestones WHERE program_id = ? AND status NOT IN ('done','cancelled')", (program_id,))]
        rec = Recorder("regulatory_research", mode() if model is None else "test", job_id=job_id)
        rec.start(conn)
        if rec.mode == "demo":
            from ..demo.fixtures_loader import fixture_regulatory

            cands, report = fixture_regulatory(program, [m["id"] for m in milestones])
            counts = store(conn, program_id, cands, report, None, rec.run_id, "fixture", {m["id"] for m in milestones})
            conn.commit()
            run = record_demo_run("regulatory_research", rec, "Demo fixtures; no retrieval or model call.")
            return {"counts": counts, "run": run, "mode": "demo"}
        items, coverage, plan = await regulatory_candidates(program, conn, rec)
        if not items:
            run = finish_ok(rec)
            return {"counts": {}, "coverage": coverage, "plan": plan, "run": run}
        cands = quarantine({f"d{i + 1}": it for i, it in enumerate(items[:30])}, rec)
        lines = []
        for cid, it in cands.items():
            jur, auth = _jur_of(it)
            st, bd = _status_binding(it)
            body = f"doc_id={cid} | jurisdiction={jur} | authority={auth} | metadata status={st}, {bd} | published={it['published_at']} | language={it.get('language')}\nTitle: {it['title']}\n{it['excerpt'][:400]}"
            lines.append(untrusted_block(cid, body))
        deps = Deps(rec=rec, program_id=program_id, candidates=cands, tool_caps={"read_document": 4})
        agent = make_agent("regulatory", RegulatoryReport, model=model, tools=[read_document])
        prompt = (f"Confirmed public profile: {json.dumps(public_profile(program))}\nOpen milestones (id, name, stage): {json.dumps([(m['id'], m['name'], m['stage']) for m in milestones])}\n"
                  f"Searched scope: {json.dumps(plan['jurisdictions'])}; product scopes: {plan['scopes']}\n\nCandidate documents:\n" + "\n".join(lines))
        report = await run_agent(agent, prompt, deps=deps, rec=rec)
        counts = store(conn, program_id, cands, report, deps, rec.run_id, "agent", {m["id"] for m in milestones})
        rec.step("verify_passages", {"kept": counts["passages_kept"], "dropped_not_verbatim": counts["passages_dropped"]})
        log_activity(conn, "research", "regulatory", program_id, counts, actor="Regulatory Research Agent")
        conn.commit()
        run = finish_ok(rec)
        return {"counts": counts, "coverage": coverage, "plan": plan, "run": run, "mode": rec.mode}
    finally:
        conn.close()
