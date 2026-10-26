"""Classification, competitor intelligence, actions, briefing, regulatory, markets, partners, assistant, URL research."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..agents import assistant as assistant_agent
from ..agents import classification as classification_agent
from ..agents.intelligence import RANKING_RULE, briefing_date, build_briefing, refresh_competitors
from ..agents.market import SCORING_RULE, refresh_market, refresh_partners
from ..agents.regulatory import refresh_regulatory
from ..agents.runner import AgentFailure
from ..config import get_settings
from ..db import get_conn, jdump, jload, log_activity, rows, utc_now
from ..jobs import manager
from ..research.cache import CacheStats
from ..research.connectors.sources import fetch_document_text
from ..research.guard import program_from_row
from ..research.http import FetchError, UnsafeURL
from ..schemas import ActionIn, ActionPatch, AskIn, ClassifyIn, CompetitorIn, ConfirmProfileIn, UrlResearchIn
from .pipelines import apply_program_patch, get_program_or_404

router = APIRouter(prefix="/api", tags=["intelligence"])


def _agent_error(exc: AgentFailure):
    raise HTTPException(503 if "not set" in str(exc) or "Demo mode" in str(exc) else 422, str(exc))


# ------------------------------------------------------------ classification


@router.post("/classify")
async def classify(body: ClassifyIn, conn=Depends(get_conn)):
    try:
        res = await classification_agent.classify(body.description, language=body.language)
    except AgentFailure as exc:
        _agent_error(exc)
    pid = conn.execute("INSERT INTO classification_proposals (program_id, input_text, proposal_json, agent_run_id, created_at) VALUES (?,?,?,?,?)",
                       (body.program_id, body.description, jdump({**res["proposal"], "_verification_notes": res["verification_notes"], "_method": res["method"]}), res["run"]["id"], utc_now())).lastrowid
    log_activity(conn, "propose", "classification", pid, {"method": res["method"]}, actor="Pipeline Classification Agent")
    return {"proposal_id": pid, **res}


@router.post("/programs/{program_id}/confirm-profile")
def confirm_profile(program_id: int, body: ConfirmProfileIn, conn=Depends(get_conn)):
    """The user's reviewed/corrected profile is applied only here, by explicit confirmation."""
    get_program_or_404(conn, program_id)
    prop = conn.execute("SELECT * FROM classification_proposals WHERE id = ?", (body.proposal_id,)).fetchone()
    if not prop:
        raise HTTPException(404, "Proposal not found")
    patch = body.profile.model_dump(exclude_unset=True)
    if "key_dates" in patch:
        patch["key_dates"] = [{"label": k["label"], "date": k["date"].isoformat()} for k in patch["key_dates"]]
    patch["profile_confirmed_at"] = utc_now()
    out = apply_program_patch(conn, program_id, patch, action="confirm_profile")
    conn.execute("UPDATE classification_proposals SET status = 'confirmed', program_id = ?, decided_at = ? WHERE id = ?", (program_id, utc_now(), body.proposal_id))
    return out


@router.post("/programs/{program_id}/unconfirm-profile")
def unconfirm(program_id: int, conn=Depends(get_conn)):
    return apply_program_patch(conn, program_id, {"profile_confirmed_at": None}, action="unconfirm_profile")


# ---------------------------------------------------------------- competitors


@router.get("/competitors")
def competitors(program_id: int | None = None, status: str | None = None, conn=Depends(get_conn)):
    sql = "SELECT c.*, p.code AS program_code FROM competitors c LEFT JOIN programs p ON p.id = c.program_id WHERE 1=1"
    params = []
    if program_id:
        sql += " AND (c.program_id = ? OR c.program_id IS NULL)"
        params.append(program_id)
    if status:
        sql += " AND c.status = ?"
        params.append(status)
    out = []
    for r in conn.execute(sql + " ORDER BY c.status, c.company", params):
        d = dict(r)
        d["species"] = jload(d.pop("species_json"), [])
        d["event_count"] = conn.execute("SELECT COUNT(*) FROM intel_events WHERE competitor_id = ?", (r["id"],)).fetchone()[0]
        out.append(d)
    return out


def _name_key(s: str | None) -> str:
    return re.sub(r"\s*\(synthetic\)\s*", " ", (s or "")).strip().lower()


@router.get("/competitors/by-pipeline")
def competitors_by_pipeline(conn=Depends(get_conn)):
    """One entry per pipeline: its tracked/suggested competitors, their product, and their latest captured movement.

    "Latest movement" is the newest non-duplicate event linked to the competitor; if none is linked, the newest event
    for the same program whose title or observation names the company. Nothing found -> None (never invented).
    """
    out = []
    for p in conn.execute("SELECT id, code, name, status FROM programs WHERE archived = 0 ORDER BY code"):
        evs = rows(conn.execute("SELECT id, competitor_id, event_type, title, observed, source_name, source_url, published_at, first_seen_at, origin FROM intel_events "
                                "WHERE program_id = ? AND duplicate_of IS NULL ORDER BY COALESCE(published_at, substr(first_seen_at,1,10)) DESC, id DESC", (p["id"],)).fetchall())
        comps = []
        for c in conn.execute("SELECT * FROM competitors WHERE program_id = ? AND status != 'dismissed' ORDER BY status DESC, company", (p["id"],)):
            key = _name_key(c["company"])
            latest = next((e for e in evs if e["competitor_id"] == c["id"]), None) or next(
                (e for e in evs if key and (key in _name_key(e["title"]) or key in _name_key(e["observed"]))), None)
            comps.append({"id": c["id"], "company": c["company"], "product": c["product"], "stage": c["stage"], "status": c["status"], "origin": c["origin"],
                          "source_url": c["source_url"], "latest": latest})
        out.append({"program_id": p["id"], "code": p["code"], "name": p["name"], "status": p["status"], "competitors": comps,
                    "unlinked_events": [e for e in evs if not e["competitor_id"]][:3]})
    return out


@router.post("/competitors", status_code=201)
def add_competitor(body: CompetitorIn, conn=Depends(get_conn)):
    now = utc_now()
    cid = conn.execute("INSERT INTO competitors (program_id, company, product, species_json, indication, mechanism, modality, geography, stage, status, source_url, notes, origin, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'user', ?, ?)",
                       (body.program_id, body.company, body.product, jdump(body.species), body.indication, body.mechanism, body.modality, body.geography, body.stage, body.status,
                        body.source_url, body.notes, now, now)).lastrowid
    log_activity(conn, "create", "competitor", cid, {"company": body.company})
    return {"id": cid}


@router.post("/competitors/{cid}/status")
def competitor_status(cid: int, status: str, conn=Depends(get_conn)):
    if status not in ("tracked", "suggested", "dismissed"):
        raise HTTPException(422, "Invalid status")
    conn.execute("UPDATE competitors SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), cid))
    log_activity(conn, f"competitor_{status}", "competitor", cid)
    return {"ok": True}


@router.get("/events")
def events(program_id: int | None = None, days: int = 90, include_duplicates: bool = False, conn=Depends(get_conn)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sql = "SELECT e.*, p.code AS program_code, c.company AS competitor FROM intel_events e LEFT JOIN programs p ON p.id = e.program_id LEFT JOIN competitors c ON c.id = e.competitor_id WHERE e.first_seen_at >= ?"
    params: list = [since]
    if program_id:
        sql += " AND e.program_id = ?"
        params.append(program_id)
    if not include_duplicates:
        sql += " AND e.duplicate_of IS NULL"
    evs = rows(conn.execute(sql + " ORDER BY COALESCE(e.published_at, substr(e.first_seen_at,1,10)) DESC, e.relevance DESC", params).fetchall())
    last = conn.execute("SELECT MAX(started_at) FROM agent_runs WHERE agent = 'external_intelligence' AND status = 'succeeded'" + (" " if not program_id else ""), ()).fetchone()[0]
    prev = conn.execute("SELECT started_at FROM agent_runs WHERE agent = 'external_intelligence' AND status = 'succeeded' ORDER BY started_at DESC LIMIT 1 OFFSET 1").fetchone()
    prev_check = prev[0] if prev else None
    for e in evs:
        e["new_since_last_check"] = bool(prev_check and e["first_seen_at"] > prev_check) or (prev_check is None)
    dup_count = conn.execute("SELECT COUNT(*) FROM intel_events WHERE duplicate_of IS NOT NULL").fetchone()[0]
    return {"events": evs, "last_check": last, "previous_check": prev_check, "duplicates_hidden": 0 if include_duplicates else dup_count,
            "coverage_note": "Events come only from the sources this app searched (listed in each run's trace). This is not a complete record of competitor activity, and the app does not know confidential plans."}


@router.post("/programs/{program_id}/research/competitors")
async def run_competitor_refresh(program_id: int, conn=Depends(get_conn)):
    p = get_program_or_404(conn, program_id)
    if not p.get("profile_confirmed_at"):
        raise HTTPException(422, "Confirm the program profile before external research.")
    return manager.start("competitor_refresh", refresh_competitors, {"program_id": program_id}, program_id=program_id)


# -------------------------------------------------------------------- actions


@router.get("/actions")
def actions(status: str | None = None, program_id: int | None = None, conn=Depends(get_conn)):
    sql = "SELECT a.*, p.code AS program_code FROM actions a LEFT JOIN programs p ON p.id = a.program_id WHERE 1=1"
    params = []
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    if program_id:
        sql += " AND a.program_id = ?"
        params.append(program_id)
    return rows(conn.execute(sql + " ORDER BY CASE a.status WHEN 'proposed' THEN 0 WHEN 'open' THEN 1 ELSE 2 END, CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.due_date", params).fetchall())


@router.post("/actions", status_code=201)
def add_action(body: ActionIn, conn=Depends(get_conn)):
    now = utc_now()
    aid = conn.execute("INSERT INTO actions (title, detail, program_id, owner, priority, due_date, status, created_by, origin, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'user', 'user', ?, ?)",
                       (body.title, body.detail, body.program_id, body.owner, body.priority, body.due_date.isoformat() if body.due_date else None, body.status, now, now)).lastrowid
    log_activity(conn, "create", "action", aid)
    return {"id": aid}


@router.patch("/actions/{aid}")
def patch_action(aid: int, body: ActionPatch, conn=Depends(get_conn)):
    patch = body.model_dump(exclude_unset=True)
    if "due_date" in patch and patch["due_date"]:
        patch["due_date"] = patch["due_date"].isoformat()
    if not patch:
        return {"ok": True}
    conn.execute(f"UPDATE actions SET {', '.join(f'{k} = ?' for k in patch)}, updated_at = ? WHERE id = ?", (*patch.values(), utc_now(), aid))
    log_activity(conn, "update", "action", aid, {"fields": sorted(patch)})
    return {"ok": True}


# ------------------------------------------------------------------- briefing


@router.get("/briefing")
def get_briefing(viewer: str = "local user", conn=Depends(get_conn)):
    day, tz = briefing_date(conn)
    r = conn.execute("SELECT * FROM briefings WHERE status != 'failed' ORDER BY generated_at DESC LIMIT 1").fetchone()
    seen = conn.execute("SELECT dismissed_at FROM briefing_views WHERE viewer = ? AND briefing_date = ?", (viewer, day)).fetchone()
    history = rows(conn.execute("SELECT id, briefing_date, generated_at, status, origin FROM briefings ORDER BY generated_at DESC LIMIT 14").fetchall())
    failed_today = conn.execute("SELECT generated_at, coverage_json FROM briefings WHERE briefing_date = ? AND status = 'failed' ORDER BY generated_at DESC LIMIT 1", (day,)).fetchone()
    if not r:
        return {"briefing": None, "today": day, "timezone": tz, "show_popup": False, "history": history, "ranking_rule": RANKING_RULE}
    b = dict(r)
    b["items"] = jload(b.pop("items_json"), {})
    b["coverage"] = jload(b.pop("coverage_json"), {})
    stale = b["briefing_date"] != day
    return {"briefing": b, "today": day, "timezone": tz, "stale": stale,
            "stale_reason": (f"Showing the most recent briefing from {b['briefing_date']}." + (" Today's retrieval failed." if failed_today else " Today's briefing has not been generated yet.")) if stale else None,
            "show_popup": not seen and not stale, "history": history, "ranking_rule": RANKING_RULE}


@router.get("/briefing/{bid}")
def briefing_by_id(bid: int, conn=Depends(get_conn)):
    r = conn.execute("SELECT * FROM briefings WHERE id = ?", (bid,)).fetchone()
    if not r:
        raise HTTPException(404, "Briefing not found")
    b = dict(r)
    b["items"] = jload(b.pop("items_json"), {})
    b["coverage"] = jload(b.pop("coverage_json"), {})
    return b


@router.post("/briefing/dismiss")
def dismiss_briefing(viewer: str = "local user", conn=Depends(get_conn)):
    day, _ = briefing_date(conn)
    conn.execute("INSERT OR REPLACE INTO briefing_views (viewer, briefing_date, dismissed_at) VALUES (?,?,?)", (viewer, day, utc_now()))
    return {"ok": True, "date": day}


@router.post("/briefing/refresh")
async def refresh_briefing():
    return manager.start("daily_briefing", build_briefing, {})


# ----------------------------------------------------------------- regulatory


@router.get("/regulatory/sources")
def reg_sources(conn=Depends(get_conn)):
    from ..research.registry import seed

    if not conn.execute("SELECT 1 FROM regulatory_sources LIMIT 1").fetchone():
        seed(conn)
    return rows(conn.execute("SELECT * FROM regulatory_sources ORDER BY jurisdiction, scope").fetchall())


@router.get("/regulatory/documents")
def reg_documents(program_id: int | None = None, conn=Depends(get_conn)):
    sql = ("SELECT d.*, a.id AS assessment_id, a.program_id, a.relevance, a.summary_en, a.is_translation, a.passages_json, a.applicability, a.unresolved_json, "
           "a.affected_milestones_json, a.review_status, a.origin AS assessment_origin FROM regulatory_documents d LEFT JOIN regulatory_assessments a ON a.document_id = d.id")
    params = []
    if program_id:
        sql += " WHERE a.program_id = ?"
        params.append(program_id)
    out = []
    for r in conn.execute(sql + " ORDER BY a.relevance DESC, d.published_date DESC", params):
        d = dict(r)
        for k in ("passages_json", "unresolved_json", "affected_milestones_json", "species_json", "topics_json"):
            d[k.replace("_json", "")] = jload(d.pop(k), [])
        out.append(d)
    return out


@router.post("/regulatory/assessments/{aid}/review")
def review_assessment(aid: int, status: str, conn=Depends(get_conn)):
    if status not in ("reviewed", "not_applicable", "needs_review"):
        raise HTTPException(422, "Invalid status")
    conn.execute("UPDATE regulatory_assessments SET review_status = ? WHERE id = ?", (status, aid))
    log_activity(conn, f"regulatory_{status}", "regulatory_assessment", aid)
    return {"ok": True}


@router.post("/programs/{program_id}/research/regulatory")
async def run_regulatory(program_id: int, conn=Depends(get_conn)):
    p = get_program_or_404(conn, program_id)
    if not p.get("profile_confirmed_at"):
        raise HTTPException(422, "Confirm the program profile before regulatory research.")
    return manager.start("regulatory_refresh", refresh_regulatory, {"program_id": program_id}, program_id=program_id)


# -------------------------------------------------------------------- markets


@router.get("/markets")
def markets(conn=Depends(get_conn)):
    obs = rows(conn.execute("SELECT * FROM market_observations ORDER BY company, period").fetchall())
    share_sets = {}
    for o in obs:
        if o["metric"] == "market_share":
            share_sets.setdefault((o["market_definition"], o["period"], o["geography"]), []).append(o)
    return {"observations": obs, "share_datasets": [{"definition": k[0], "period": k[1], "geography": k[2], "rows": v} for k, v in share_sets.items()],
            "share_chart_rule": "A donut/pie chart is drawn only when market-share rows share the same market definition, geography, period and source basis. Otherwise a sourced revenue comparison is shown.",
            "caveat": "Company revenue is not market share. Totals cover all species and products of each company."}


@router.post("/markets/refresh")
async def market_refresh():
    return manager.start("market_refresh", refresh_market, {})


@router.get("/partners")
def partners(program_id: int | None = None, conn=Depends(get_conn)):
    sql = "SELECT pc.*, p.code AS program_code FROM partner_candidates pc LEFT JOIN programs p ON p.id = pc.program_id"
    params = []
    if program_id:
        sql += " WHERE pc.program_id = ?"
        params.append(program_id)
    out = []
    for r in conn.execute(sql + " ORDER BY fit_score DESC", params):
        d = dict(r)
        for k in ("evidence_json", "criteria_json", "gaps_json"):
            d[k.replace("_json", "")] = jload(d.pop(k), [] if k != "criteria_json" else {})
        out.append(d)
    return {"partners": out, "scoring_rule": SCORING_RULE, "note": "Potential partners based on public evidence. Not confirmed interest, deal terms, or contacts."}


@router.post("/programs/{program_id}/research/partners")
async def run_partners(program_id: int, conn=Depends(get_conn)):
    p = get_program_or_404(conn, program_id)
    if not p.get("profile_confirmed_at"):
        raise HTTPException(422, "Confirm the program profile before partner research.")
    return manager.start("partner_refresh", refresh_partners, {"program_id": program_id}, program_id=program_id)


@router.post("/research/url")
async def research_url(body: UrlResearchIn, company: str | None = None, criterion: str | None = None, conn=Depends(get_conn)):
    """User-supplied public URL: fetched safely and stored as partner evidence (no paid search needed)."""
    get_program_or_404(conn, body.program_id)
    if get_settings().is_demo:
        raise HTTPException(422, "URL research performs real retrieval; switch to live mode.")
    try:
        doc = await fetch_document_text(body.url, stats=CacheStats(), max_chars=4000)
    except UnsafeURL as exc:
        raise HTTPException(422, f"URL rejected: {exc}")
    except FetchError as exc:
        raise HTTPException(502, f"Could not retrieve the page: {exc}")
    title = (doc["text"].strip().splitlines() or [body.url])[0][:200]
    if company:
        r = conn.execute("SELECT evidence_json FROM partner_candidates WHERE program_id = ? AND company = ?", (body.program_id, company)).fetchone()
        ev = jload(r["evidence_json"], []) if r else []
        ev.append({"criterion": criterion or "stated_strategic_interest", "fact": title, "source_name": "User-supplied URL", "source_url": doc["final_url"],
                   "retrieved_at": doc["retrieved_at"], "excerpt": doc["text"][:300], "user_supplied": True})
        conn.execute("INSERT INTO partner_candidates (program_id, company, evidence_json, origin, updated_at) VALUES (?,?,?, 'user', ?) ON CONFLICT(program_id, company) DO UPDATE SET evidence_json = excluded.evidence_json, updated_at = excluded.updated_at",
                     (body.program_id, company, jdump(ev), utc_now()))
    log_activity(conn, "url_research", "research", body.program_id, {"host": doc["final_url"].split("/")[2]})
    return {"title": title, "final_url": doc["final_url"], "retrieved_at": doc["retrieved_at"], "excerpt": doc["text"][:800], "sha256": doc["sha256"], "untrusted": True}


# ------------------------------------------------------------------ assistant


@router.post("/assistant/ask")
async def ask(body: AskIn, conn=Depends(get_conn)):
    try:
        res = await assistant_agent.ask(body.question, program_id=body.program_id, language=body.language)
    except AgentFailure as exc:
        _agent_error(exc)
    log_activity(conn, "ask", "assistant", res["run"]["id"], {"method": res["method"]}, actor="Planning Assistant")
    return res


# ----------------------------------------------------------------------- jobs


@router.get("/jobs")
def jobs(limit: int = 30, conn=Depends(get_conn)):
    out = []
    for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (min(limit, 200),)):
        d = dict(r)
        d["params"] = jload(d.pop("params_json"), {})
        d["result"] = jload(d.pop("result_json"), {})
        out.append(d)
    return out


@router.get("/jobs/{jid}")
def job(jid: int):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int):
    return {"cancelled": manager.cancel(jid)}


__all__ = ["router", "program_from_row", "date"]
