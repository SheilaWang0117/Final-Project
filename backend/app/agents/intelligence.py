"""External Intelligence Agent: competitor events and the daily briefing.

Application code retrieves candidates from public sources using only
guard-checked, non-confidential queries. The agent classifies and explains
them; it can only read candidates it was given. Validated results are stored
by this module (the agent itself has no write tools).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic_ai import RunContext

from ..config import get_settings
from ..db import connect, get_setting, jdump, jload, log_activity, utc_now
from ..research.connectors import sources as S
from ..research.dedupe import canonical_url, dedupe_items, similar_titles, url_key
from ..research.guard import build_queries, program_from_row, public_profile, species_terms
from ..research.injection import quarantine, scrub
from .common import Deps, make_agent, mode
from .runner import AgentFailure, Recorder, finish_ok, record_demo_run, run_agent, traced, untrusted_block
from .schemas import BriefingDraft, IntelligenceReport

MAX_CANDIDATES = 30


class Cancelled(RuntimeError):
    pass


# ----------------------------------------------------------------- retrieval


async def _gather(rec: Recorder, tasks: dict[str, "asyncio.Future"]) -> tuple[list[dict], dict]:
    names = list(tasks)
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    items, coverage = [], {}
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            coverage[name] = {"ok": False, "error": f"{type(res).__name__}: {str(res)[:160]}"}
            rec.step(f"retrieve:{name}", ok=False, error=coverage[name]["error"])
        else:
            coverage[name] = {"ok": True, "items": len(res)}
            rec.step(f"retrieve:{name}", {"items": len(res), "cache": "hit" if res and res[0].get("from_cache") else "miss"})
            items.extend(res)
    return items, coverage


def _filter_terms(program: dict) -> list[str]:
    p = public_profile(program)
    terms = species_terms(p.get("species", []))
    return terms


async def competitor_candidates(program: dict, conn, rec: Recorder) -> tuple[list[dict], dict, list[str]]:
    queries = build_queries(program, conn)
    rec.step("public_queries", {"queries": queries, "note": "Built only from confirmed public profile fields; guard-checked."})
    if not queries:
        raise AgentFailure("No safe public queries could be built. Confirm species/indication/modality in the profile.")
    since = date.today() - timedelta(days=365)
    tasks = {}
    for i, q in enumerate(queries[:3]):
        tasks[f"europepmc:{i}"] = S.search_europepmc(q, stats=rec.cache, limit=8, since=since)
    tasks["clinicaltrials"] = S.search_clinicaltrials(queries[0], stats=rec.cache, limit=6)
    tasks["sec_fulltext"] = S.sec_full_text(f'"{queries[0]}"', stats=rec.cache, limit=6, since=since)
    for key in ("vpn", "dvm360", "fierce_biotech", "biopharma_dive"):
        tasks[f"rss:{key}"] = S.fetch_feed(key, stats=rec.cache)
    items, coverage = await _gather(rec, tasks)
    sp = _filter_terms(program)
    tracked = [r["company"].lower() for r in conn.execute("SELECT company FROM competitors WHERE status = 'tracked' AND (program_id = ? OR program_id IS NULL)", (program["id"],))]
    kept = []
    for it in items:
        if it["connector"].startswith("rss:"):
            blob = (it["title"] + " " + it["excerpt"]).lower()
            if not (any(t in blob for t in sp) or any(c in blob for c in tracked)):
                continue  # general news is filtered to the program's species or tracked companies
        kept.append(it)
    unique, dups = dedupe_items(kept)
    rec.step("dedupe", {"retrieved": len(items), "kept_after_filter": len(kept), "unique": len(unique), "duplicates": len(dups)})
    return unique[:MAX_CANDIDATES], coverage, queries


def _candidate_block(cands: dict[str, dict]) -> str:
    lines = []
    for cid, it in cands.items():
        body = f"id={cid} | source={it['source_name']} | kind={it['kind']} | published={it['published_at'] or 'unknown'}\nTitle: {it['title']}\nExcerpt: {it['excerpt'][:600]}"
        lines.append(untrusted_block(cid, body))
    return "\n".join(lines)


@traced
async def read_candidate(ctx: RunContext[Deps], item_id: str) -> dict:
    """Read the full public text of one listed candidate (by item_id). Untrusted content."""
    it = ctx.deps.candidates.get(item_id)
    if not it:
        ctx.deps.rec.blocked.append({"tool": "read_candidate", "requested": item_id[:80], "reason": "not an approved candidate"})
        return {"error": "Unknown item_id. Only listed candidates can be read."}
    doc = await S.fetch_document_text(it["url"], stats=ctx.deps.rec.cache, max_chars=6000)
    doc["text"], removed = scrub(doc["text"])
    if removed:
        ctx.deps.rec.step("scrub", {"item_id": item_id, "lines_removed": removed}, ok=False, error="instruction-like lines removed from retrieved text")
    ctx.deps.read_texts[item_id] = doc["text"]
    ctx.deps.rec.source(it["title"], it["url"], doc["retrieved_at"], doc["from_cache"])
    return {"item_id": item_id, "content": untrusted_block(item_id, doc["text"]), "truncated": doc["truncated"]}


# --------------------------------------------------------------- persistence


def store_events(conn, program_id: int, cands: dict[str, dict], report: IntelligenceReport, run_id: int | None, origin: str) -> dict:
    now = utc_now()
    counts = {"new": 0, "updated": 0, "unchanged": 0, "duplicates": 0, "actions_proposed": 0, "competitors_suggested": 0, "rejected": 0}
    for a in report.assessments:
        it = cands.get(a.item_id)
        if not it or not a.relevant or a.relevance < 40:
            counts["rejected"] += 1 if not it else 0
            continue
        key = url_key(it["url"])
        existing = conn.execute("SELECT * FROM intel_events WHERE program_id = ? AND dedupe_key = ?", (program_id, key)).fetchone()
        if existing:
            if existing["content_hash"] != it["content_hash"]:
                conn.execute("UPDATE intel_events SET observed=?, interpretation=?, relevance=?, relevance_reason=?, content_hash=?, last_seen_at=?, retrieved_at=?, change_note=?, agent_run_id=? WHERE id=?",
                             (a.observed, a.interpretation, a.relevance, a.relevance_reason, it["content_hash"], now, it["retrieved_at"] or now, f"Source content changed since {existing['retrieved_at'][:10]}", run_id, existing["id"]))
                counts["updated"] += 1
            else:
                conn.execute("UPDATE intel_events SET last_seen_at = ? WHERE id = ?", (now, existing["id"]))
                counts["unchanged"] += 1
            continue
        dup_of = None
        for r in conn.execute("SELECT id, title FROM intel_events WHERE program_id = ? AND duplicate_of IS NULL AND first_seen_at >= ?", (program_id, (datetime.now(timezone.utc) - timedelta(days=30)).isoformat())):
            if similar_titles(r["title"], it["title"]):
                dup_of = r["id"]
                break
        comp_id = None
        if a.company:
            c = conn.execute("SELECT id, status FROM competitors WHERE lower(company) = lower(?) AND (program_id = ? OR program_id IS NULL)", (a.company, program_id)).fetchone()
            if c:
                comp_id = c["id"]
            elif a.relevance >= 60:
                comp_id = conn.execute(
                    "INSERT INTO competitors (program_id, company, product, status, match_reason, source_url, origin, created_at, updated_at) VALUES (?,?,?, 'suggested', ?, ?, ?, ?, ?)",
                    (program_id, a.company, a.product, f"AI-suggested from: {it['title'][:120]} ({a.relevance_reason[:120]})", it["url"], origin, now, now)).lastrowid
                counts["competitors_suggested"] += 1
        eid = conn.execute(
            "INSERT INTO intel_events (program_id, competitor_id, event_type, title, observed, interpretation, possible_next_move, suggested_action, relevance, relevance_reason, "
            "source_name, source_url, published_at, event_date, retrieved_at, content_hash, dedupe_key, duplicate_of, first_seen_at, last_seen_at, agent_run_id, origin) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (program_id, comp_id, a.event_type, it["title"], a.observed, a.interpretation, a.possible_next_move, a.suggested_action, a.relevance, a.relevance_reason,
             it["source_name"], it["url"], it["published_at"], None, it["retrieved_at"] or now, it["content_hash"], key, dup_of, now, now, run_id, origin)).lastrowid
        counts["duplicates" if dup_of else "new"] += 1
        if a.suggested_action and not dup_of and a.relevance >= 55:
            conn.execute("INSERT INTO actions (title, detail, program_id, source_type, source_id, priority, status, created_by, origin, created_at, updated_at) VALUES (?,?,?,?,?,?, 'proposed', 'agent', ?, ?, ?)",
                         (a.suggested_action[:300], f"Proposed by the External Intelligence Agent from: {it['title'][:200]}", program_id, "intel_event", eid,
                          "high" if a.relevance >= 80 else "medium", origin, now, now))
            counts["actions_proposed"] += 1
    return counts


# ------------------------------------------------------------------- refresh


async def refresh_competitors(program_id: int, *, job_id: int | None = None, model=None, cancelled=lambda: False) -> dict:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM programs WHERE id = ?", (program_id,)).fetchone()
        if not r:
            raise AgentFailure("Program not found")
        program = program_from_row(r)
        if not program.get("profile_confirmed_at"):
            raise AgentFailure("Confirm the program profile before external research, so only reviewed, non-confidential fields are used.")
        rec = Recorder("external_intelligence", mode() if model is None else "test", job_id=job_id)
        rec.start(conn)
        if rec.mode == "demo":
            from ..demo.fixtures_loader import fixture_report

            cands, report = fixture_report("competitor_items", program)
            counts = store_events(conn, program_id, cands, report, rec.run_id, "fixture")
            conn.commit()
            run = record_demo_run("external_intelligence", rec, "Demo fixtures (synthetic research items); no retrieval or model call.")
            return {"counts": counts, "coverage": {"fixtures": {"ok": True}}, "run": run, "mode": "demo"}
        cands_list, coverage, queries = await competitor_candidates(program, conn, rec)
        if cancelled():
            raise Cancelled()
        if not cands_list:
            run = finish_ok(rec, status="succeeded", error=None)
            return {"counts": {"new": 0}, "coverage": coverage, "run": run, "queries": queries, "mode": rec.mode}
        cands = quarantine({f"c{i + 1}": it for i, it in enumerate(cands_list)}, rec)
        tracked = [dict(x) for x in conn.execute("SELECT company, product FROM competitors WHERE status = 'tracked' AND (program_id = ? OR program_id IS NULL)", (program_id,))]
        deps = Deps(rec=rec, program_id=program_id, candidates=cands, tool_caps={"read_candidate": 3})
        agent = make_agent("intelligence", IntelligenceReport, model=model, tools=[read_candidate])
        prompt = (f"Program public profile (confirmed by the team): {json.dumps(public_profile(program))}\n"
                  f"Tracked competitors (public names): {json.dumps(tracked)}\n\nCandidates:\n{_candidate_block(cands)}")
        report = await run_agent(agent, prompt, deps=deps, rec=rec)
        if report.injection_detected:
            rec.step("injection_flag", {"note": "Model reported instruction-like text in retrieved content; ignored."}, ok=False)
        counts = store_events(conn, program_id, cands, report, rec.run_id, "agent")
        for it in cands.values():
            rec.source(it["title"], it["url"], it["retrieved_at"], it.get("from_cache"))
        log_activity(conn, "research", "intel_events", program_id, counts, actor="External Intelligence Agent")
        conn.commit()
        run = finish_ok(rec)
        return {"counts": counts, "coverage": coverage, "queries": queries, "run": run, "mode": rec.mode}
    finally:
        conn.close()


# ------------------------------------------------------------------ briefing

AUTHORITY = {"FDA press releases": 100, "EMA news": 100, "Federal Register (US)": 100, "ClinicalTrials.gov": 85, "Europe PMC": 80, "SEC EDGAR": 85}
RANKING_RULE = (
    "score = 0.45 x significance (AI, 0-100) + 0.35 x pipeline relevance (AI, 0-100) + 0.10 x recency (100 today, falling to 0 after 3 days) "
    "+ 0.10 x source authority (official regulator 100, registry/filing 85, publication index 80, trade press 60). "
    "The lead story is the highest-scoring item. AI scores are judgments; the formula is fixed and shown for transparency."
)


def briefing_date(conn) -> tuple[str, str]:
    tz = get_setting(conn, "timezone", get_settings().default_timezone) or get_settings().default_timezone
    try:
        z = ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        tz, z = "UTC", ZoneInfo("UTC")
    return datetime.now(z).date().isoformat(), tz


def score(pick: dict, item: dict, today: date) -> dict:
    pub = item.get("published_at")
    age = (today - date.fromisoformat(pub)).days if pub else 2
    recency = max(0, 100 - max(0, age) * 33)
    authority = AUTHORITY.get(item["source_name"], 60)
    total = round(0.45 * pick["significance"] + 0.35 * pick["pipeline_relevance"] + 0.10 * recency + 0.10 * authority, 1)
    return {"total": total, "significance": pick["significance"], "pipeline_relevance": pick["pipeline_relevance"], "recency": recency, "authority": authority}


def internal_section(conn, today: date) -> list[dict]:
    """Deterministic internal reminders (never sent to a model)."""
    out = []
    soon = (today + timedelta(days=30)).isoformat()
    for r in conn.execute("SELECT m.name, m.planned_end, m.status, p.code FROM milestones m JOIN programs p ON p.id = m.program_id WHERE p.archived = 0 AND m.status NOT IN ('done','cancelled') AND m.planned_end IS NOT NULL AND m.planned_end <= ? ORDER BY m.planned_end", (soon,)):
        overdue = r["planned_end"] < today.isoformat()
        out.append({"kind": "milestone", "text": f"{r['code']}: '{r['name']}' {'was due' if overdue else 'is due'} {r['planned_end']}", "level": "warning" if overdue else "info"})
    for r in conn.execute("SELECT title, due_date FROM actions WHERE status IN ('open','proposed') AND due_date IS NOT NULL AND due_date <= ? ORDER BY due_date LIMIT 5", (soon,)):
        out.append({"kind": "action", "text": f"Action due {r['due_date']}: {r['title']}", "level": "info"})
    try:
        from ..finance import ledger

        s = ledger.summary(conn)
        fc = s["forecast"]
        if not s["cash"]["complete"]:
            out.append({"kind": "finance", "text": "Cash balance is incomplete (reconcile accounts to calculate runway).", "level": "warning"})
        elif fc["below_reserve_month"]:
            out.append({"kind": "finance", "text": f"Forecast cash falls below the minimum reserve in {fc['below_reserve_month']}.", "level": "warning"})
        n_open = conn.execute("SELECT COUNT(*) FROM commitments WHERE status = 'open' AND expected_payment_date <= ?", (soon,)).fetchone()[0]
        if n_open:
            out.append({"kind": "finance", "text": f"{n_open} commitment payment(s) expected in the next 30 days.", "level": "info"})
    except Exception as exc:  # noqa: BLE001
        out.append({"kind": "finance", "text": f"Financial check unavailable: {type(exc).__name__}", "level": "warning"})
    return out


async def build_briefing(*, job_id: int | None = None, model=None) -> dict:
    conn = connect()
    try:
        day, tz = briefing_date(conn)
        today = date.fromisoformat(day)
        rec = Recorder("daily_briefing", mode() if model is None else "test", job_id=job_id)
        rec.start(conn)
        programs = [program_from_row(r) for r in conn.execute("SELECT * FROM programs WHERE archived = 0 AND profile_confirmed_at IS NOT NULL")]
        internal = internal_section(conn, today)
        if rec.mode == "demo":
            from ..demo.fixtures_loader import fixture_briefing

            items = fixture_briefing(today)
            bid = conn.execute("INSERT INTO briefings (briefing_date, timezone, generated_at, status, items_json, ranking_rule, coverage_json, agent_run_id, origin) VALUES (?,?,?,?,?,?,?,?, 'fixture')",
                               (day, tz, utc_now(), "fresh", jdump({"stories": items, "internal": internal}), RANKING_RULE, jdump({"fixtures": {"ok": True}}), rec.run_id)).lastrowid
            conn.commit()
            record_demo_run("daily_briefing", rec, "Demo fixtures; no retrieval or model call.")
            return {"briefing_id": bid, "mode": "demo"}
        tasks = {f"rss:{k}": S.fetch_feed(k, stats=rec.cache) for k in S.NEWS_FEEDS}
        tasks["federal_register:animal"] = S.search_federal_register("animal drug OR veterinary", stats=rec.cache, limit=8, since=today - timedelta(days=7))
        items, coverage = await _gather(rec, tasks)
        cutoff = (today - timedelta(days=3)).isoformat()
        recent = [it for it in items if (it["published_at"] or day) >= cutoff]
        unique, dups = dedupe_items(recent)
        rec.step("dedupe", {"retrieved": len(items), "recent": len(recent), "unique": len(unique), "duplicates": len(dups)})
        if not unique:
            status = "failed" if not any(c["ok"] for c in coverage.values()) else "partial"
            bid = conn.execute("INSERT INTO briefings (briefing_date, timezone, generated_at, status, items_json, ranking_rule, coverage_json, agent_run_id) VALUES (?,?,?,?,?,?,?,?)",
                               (day, tz, utc_now(), status, jdump({"stories": [], "internal": internal}), RANKING_RULE, jdump(coverage), rec.run_id)).lastrowid
            conn.commit()
            finish_ok(rec, status="succeeded")
            return {"briefing_id": bid, "status": status}
        # animal-health and regulatory feeds first so they survive the cap
        unique.sort(key=lambda it: (0 if it["connector"] in ("rss:vpn", "rss:dvm360", "rss:fda_press", "rss:ema_news") or it["connector"].startswith("federal") else 1))
        cands = quarantine({f"n{i + 1}": it for i, it in enumerate(unique[:40])}, rec)
        profiles = [public_profile(p) for p in programs]
        agent = make_agent("briefing", BriefingDraft, model=model)
        prompt = f"Today is {day} ({tz}). Program public profiles: {json.dumps(profiles)}\n\nCandidates:\n{_candidate_block(cands)}"
        draft = await run_agent(agent, prompt, deps=Deps(rec=rec, candidates=cands), rec=rec)
        stories = []
        for p in draft.picks:
            it = cands.get(p.item_id)
            if not it:
                continue
            sc = score(p.model_dump(), it, today)
            stories.append({"section": p.section, "title": it["title"], "summary": p.summary, "why_it_matters": p.why_it_matters, "source": it["source_name"],
                            "url": it["url"], "published_at": it["published_at"], "retrieved_at": it["retrieved_at"], "score": sc})
            rec.source(it["title"], it["url"], it["retrieved_at"], it.get("from_cache"))
        stories.sort(key=lambda s: -s["score"]["total"])
        if stories:
            stories[0]["lead"] = True
        status = "fresh" if all(c["ok"] for c in coverage.values()) else "partial"
        bid = conn.execute("INSERT INTO briefings (briefing_date, timezone, generated_at, status, items_json, ranking_rule, coverage_json, agent_run_id) VALUES (?,?,?,?,?,?,?,?)",
                           (day, tz, utc_now(), status, jdump({"stories": stories, "internal": internal, "injection_detected": draft.injection_detected}), RANKING_RULE, jdump(coverage), rec.run_id)).lastrowid
        log_activity(conn, "briefing", "briefing", bid, {"stories": len(stories), "status": status}, actor="External Intelligence Agent")
        conn.commit()
        run = finish_ok(rec)
        return {"briefing_id": bid, "status": status, "stories": len(stories), "coverage": coverage, "run": run}
    finally:
        conn.close()


__all__ = ["refresh_competitors", "build_briefing", "store_events", "canonical_url", "jload", "Cancelled"]
