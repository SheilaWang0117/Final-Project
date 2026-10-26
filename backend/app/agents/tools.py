"""Read-only business tools for agents.

Every tool opens the database with SQLite's read-only URI mode, so an agent
cannot modify records even if a tool had a bug. Financial values are computed
by `app.finance` and returned as formatted strings; the model only quotes them.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

from pydantic_ai import RunContext

from ..config import get_settings
from ..db import jload
from ..finance import calc, ledger
from ..finance.money import fmt
from .common import Deps
from .runner import traced


@contextmanager
def ro_conn():
    path = get_settings().database_path
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _m(minor, ccy):
    return fmt(minor, ccy) if minor is not None else "unknown"


def _program_brief(r) -> dict:
    return {"id": r["id"], "code": r["code"], "name": r["name"], "use_type": r["use_type"], "species": jload(r["species_json"], []),
            "indication": r["indication"], "modality": r["modality"], "target": r["target"], "stage": r["stage"], "status": r["status"],
            "priority": r["priority"], "jurisdictions": jload(r["jurisdictions_json"], []), "origin": r["origin"]}


@traced
def get_pipeline(ctx: RunContext[Deps], program_id: int | None = None) -> dict:
    """List active programs (or one program) with stage, species, indication and next open milestone."""
    with ro_conn() as conn:
        sql = "SELECT * FROM programs WHERE archived = 0" + (" AND id = ?" if program_id else "")
        progs = [_program_brief(r) for r in conn.execute(sql, (program_id,) if program_id else ())]
        for p in progs:
            nxt = conn.execute("SELECT id, name, planned_end, status FROM milestones WHERE program_id = ? AND status NOT IN ('done','cancelled') ORDER BY planned_end IS NULL, planned_end LIMIT 1", (p["id"],)).fetchone()
            p["next_milestone"] = dict(nxt) if nxt else None
        return {"programs": progs}


@traced
def list_milestones(ctx: RunContext[Deps], program_id: int) -> dict:
    """Milestones for a program with dates, status, dependencies and baseline slip."""
    with ro_conn() as conn:
        out = []
        for r in conn.execute("SELECT * FROM milestones WHERE program_id = ? ORDER BY sort_order, planned_start", (program_id,)):
            out.append({"id": r["id"], "name": r["name"], "status": r["status"], "planned_start": r["planned_start"], "planned_end": r["planned_end"],
                        "baseline_end": r["baseline_end"], "depends_on": jload(r["depends_on_json"], []), "decision_point": bool(r["is_decision_point"]),
                        "overdue": bool(r["planned_end"] and r["planned_end"] < date.today().isoformat() and r["status"] not in ("done", "cancelled"))})
        return {"program_id": program_id, "milestones": out}


@traced
def get_budget_summary(ctx: RunContext[Deps], program_id: int | None = None) -> dict:
    """Budget vs actual vs open commitments vs remaining forecast, by program and milestone (deterministic)."""
    with ro_conn() as conn:
        inp, _ = ledger.forecast_inputs(conn)
        st = calc.budget_status(inp.lines, inp.milestones, inp.txns, inp.commitments, inp.fx, inp.reporting, inp.as_of, inp.rules)
        names = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM programs")}
        mnames = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM milestones")}
        ccy = inp.reporting
        rows = []
        for b in st["buckets"]:
            if program_id and b["program_id"] != program_id:
                continue
            rows.append({"program": names.get(b["program_id"], "Shared/company"), "milestone": mnames.get(b["milestone_id"]), "category": b["category"],
                         "approved": _m(b["approved_minor"], ccy), "planned": _m(b["planned_minor"], ccy), "actual_paid": _m(b["actual_minor"], ccy),
                         "open_commitments": _m(b["open_commitments_minor"], ccy), "remaining_forecast": _m(b["remaining_forecast_minor"], ccy),
                         "overrun_vs_budget_incl_contingency": _m(b["overrun_minor"], ccy), "unapproved_lines": b["unapproved_lines"]})
        by_prog = []
        for p in calc.rollup(st["buckets"], "program_id"):
            if program_id and p["program_id"] != program_id:
                continue
            over = p["variance_vs_approved_minor"]
            by_prog.append({"program": names.get(p["program_id"], "Shared/company"), "approved": _m(p["approved_minor"], ccy), "actual_paid": _m(p["actual_minor"], ccy),
                            "open_commitments": _m(p["open_commitments_minor"], ccy), "forecast_at_completion": _m(p["forecast_at_completion_minor"], ccy),
                            "forecast_on_approved_lines": _m(p["forecast_on_approved_minor"], ccy), "unapproved_estimates_not_in_variance": _m(p["unapproved_forecast_minor"], ccy),
                            "forecast_minus_approved": _m(over, ccy) if over is not None else "no approved budget",
                            "forecast_vs_approved_pct": (f"{(over * 100 / p['approved_minor']):.1f}%" if over is not None and p["approved_minor"] else "n/a")})
        return {"currency": ccy, "as_of": inp.as_of.isoformat(), "by_program": by_prog, "lines": rows[:40],
                "unallocated_paid_spend": _m(st["unallocated_minor"], ccy), "shared_without_rule": _m(st["shared_without_rule_minor"], ccy),
                "definition": st["definition"], "issues": st["issues"]}


def _forecast_view(fc: dict, ccy: str) -> dict:
    return {"as_of": fc["as_of"], "start_cash": _m(fc["start_cash_minor"], ccy), "minimum_reserve": _m(fc["reserve_minor"], ccy),
            "month_cash_falls_below_reserve": fc["below_reserve_month"] or f"not within {fc['horizon_months']} months",
            "month_cash_falls_below_zero": fc["cash_out_month"] or f"not within {fc['horizon_months']} months",
            "lowest_projected_cash": _m(fc["min_cash_minor"], ccy),
            "months": [{"month": m["month"], "outflows": _m(m["total_outflows_minor"], ccy), "inflows": _m(m["inflows"], ccy), "closing_cash": _m(m["closing_minor"], ccy)} for m in fc["months"]],
            "issues": fc["issues"][:10], "method": fc["method"]}


@traced
def calculate_cash_forecast(ctx: RunContext[Deps]) -> dict:
    """Current reconciled cash, gross/net burn, simple runway, and the dated monthly cash forecast (deterministic)."""
    with ro_conn() as conn:
        s = ledger.summary(conn)
    ccy = s["currency"]
    return {"currency": ccy, "available_cash": _m(s["cash"]["available_cash_minor"], ccy), "cash_complete": s["cash"]["complete"],
            "burn_period": f"{s['burn']['period_start']} for {s['burn']['months']} months",
            "gross_burn_per_month": _m(s["burn"]["gross_burn_monthly_minor"], ccy), "net_burn_per_month": _m(s["burn"]["net_burn_monthly_minor"], ccy),
            "simple_runway_months": s["simple_runway"]["months"] or s["simple_runway"]["status"], "simple_runway_note": s["simple_runway"]["note"],
            "forecast": _forecast_view(s["forecast"], ccy), "data_warnings": [i["message"] for i in s["completeness"]][:10], "definitions": s["definitions"]}


@traced
def check_milestone_funding(ctx: RunContext[Deps], milestone_id: int) -> dict:
    """Whether a milestone (with unfinished prerequisites) is funded under the baseline forecast, and any funding gap."""
    with ro_conn() as conn:
        inp, _ = ledger.forecast_inputs(conn)
    try:
        f = calc.milestone_funding(milestone_id, inp)
    except KeyError:
        return {"error": "milestone not found"}
    ccy = f["currency"]
    return {"milestone": f["milestone"], "planned_end": f["planned_end"], "funded": f["funded"], "direct_cost_to_reach": _m(f["direct_cost_to_reach_minor"], ccy),
            "lowest_projected_cash_through_milestone": _m(f["min_projected_cash_through_milestone_minor"], ccy), "minimum_reserve": _m(f["reserve_minor"], ccy),
            "funding_gap": _m(f["funding_gap_minor"], ccy), "dependency_chain": f["dependency_chain"], "data_gaps": f["gaps"], "definition": f["definition"]}


@traced
def simulate_milestone_delay(ctx: RunContext[Deps], milestone_id: int, months: int) -> dict:
    """Compute (without saving) how delaying a milestone by N months (and its dependents) changes the cash forecast."""
    if not -24 <= months <= 24:
        return {"error": "months must be between -24 and 24"}
    with ro_conn() as conn:
        inp, _ = ledger.forecast_inputs(conn)
        name = conn.execute("SELECT name FROM milestones WHERE id = ?", (milestone_id,)).fetchone()
    if not name:
        return {"error": "milestone not found"}
    base = calc.forecast(inp)
    scen = calc.forecast(calc.apply_scenario(inp, {"milestone_shifts": {str(milestone_id): months}}))
    cmp = calc.compare(base, scen)
    ccy = inp.reporting
    return {"milestone": name[0], "shift_months": months, "baseline_unchanged": True,
            "below_reserve_month": cmp["below_reserve_month"], "cash_out_month": cmp["cash_out_month"],
            "lowest_cash": {"base": _m(cmp["min_cash_minor"]["base"], ccy), "scenario": _m(cmp["min_cash_minor"]["scenario"], ccy)},
            "cash_at_horizon": {"base": _m(cmp["cash_at_horizon_minor"]["base"], ccy), "scenario": _m(cmp["cash_at_horizon_minor"]["scenario"], ccy)},
            "note": "Dependent milestones shift too; commitments tied to the milestone move with it. Calculated on a copy."}


@traced
def compare_scenario(ctx: RunContext[Deps], scenario_id: int) -> dict:
    """Compare a saved scenario with the approved baseline (calculated on a copy)."""
    with ro_conn() as conn:
        r = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if not r:
            return {"error": "scenario not found"}
        inp, _ = ledger.forecast_inputs(conn)
    a = jload(r["assumptions_json"], {})
    cmp = calc.compare(calc.forecast(inp), calc.forecast(calc.apply_scenario(inp, a)))
    ccy = inp.reporting
    return {"scenario": r["name"], "assumptions": a, "below_reserve_month": cmp["below_reserve_month"], "cash_out_month": cmp["cash_out_month"],
            "lowest_cash": {"base": _m(cmp["min_cash_minor"]["base"], ccy), "scenario": _m(cmp["min_cash_minor"]["scenario"], ccy)},
            "cash_at_horizon": {"base": _m(cmp["cash_at_horizon_minor"]["base"], ccy), "scenario": _m(cmp["cash_at_horizon_minor"]["scenario"], ccy)}}


@traced
def list_scenarios(ctx: RunContext[Deps]) -> dict:
    """Saved scenarios and their assumptions."""
    with ro_conn() as conn:
        return {"scenarios": [{"id": r["id"], "name": r["name"], "kind": r["kind"], "assumptions": jload(r["assumptions_json"], {})} for r in conn.execute("SELECT * FROM scenarios")]}


@traced
def get_competitor_events(ctx: RunContext[Deps], program_id: int | None = None, days: int = 30) -> dict:
    """Stored competitor/field events with sources, from the last N days (observed vs interpretation kept separate)."""
    since = (date.today() - timedelta(days=max(1, min(days, 365)))).isoformat()
    with ro_conn() as conn:
        sql = "SELECT e.*, p.code FROM intel_events e LEFT JOIN programs p ON p.id = e.program_id WHERE e.duplicate_of IS NULL AND COALESCE(e.published_at, e.first_seen_at) >= ?"
        params: list = [since]
        if program_id:
            sql += " AND e.program_id = ?"
            params.append(program_id)
        evs = [{"program": r["code"], "type": r["event_type"], "title": r["title"], "observed": r["observed"], "interpretation_ai": r["interpretation"],
                "relevance": r["relevance"], "source": r["source_name"], "url": r["source_url"], "published": r["published_at"], "retrieved": r["retrieved_at"],
                "origin": r["origin"]} for r in conn.execute(sql + " ORDER BY relevance DESC LIMIT 15", params)]
    for e in evs:
        ctx.deps.rec.source(e["title"], e["url"], e["retrieved"])
    return {"since": since, "events": evs, "note": "Only events captured by this app's searches; not a complete record of competitor activity."}


@traced
def get_regulatory_documents(ctx: RunContext[Deps], program_id: int | None = None) -> dict:
    """Official regulatory documents assessed for programs, with status, binding/guidance, and applicability notes."""
    with ro_conn() as conn:
        sql = ("SELECT d.*, a.relevance, a.applicability, a.summary_en, a.unresolved_json, a.review_status, a.program_id, a.affected_milestones_json FROM regulatory_documents d "
               "JOIN regulatory_assessments a ON a.document_id = d.id")
        params = []
        if program_id:
            sql += " WHERE a.program_id = ?"
            params.append(program_id)
        docs = [{"title": r["title"], "authority": r["authority"], "jurisdiction": r["jurisdiction"], "status": r["doc_status"], "binding": r["binding"],
                 "published": r["published_date"], "url": r["url"], "retrieved": r["retrieved_at"], "relevance": r["relevance"],
                 "applicability_ai": r["applicability"], "summary_ai": r["summary_en"], "open_questions": jload(r["unresolved_json"], []),
                 "changed_at": r["changed_at"], "review_status": r["review_status"], "affected_milestone_ids": jload(r["affected_milestones_json"], [])}
                for r in conn.execute(sql + " ORDER BY a.relevance DESC LIMIT 12", params)]
    for d in docs:
        ctx.deps.rec.source(d["title"], d["url"], d["retrieved"])
    return {"documents": docs, "note": "Research summaries, not regulatory determinations. Coverage limited to the searched official sources."}


@traced
def get_market_observations(ctx: RunContext[Deps]) -> dict:
    """Sourced market observations (e.g., reported company revenue) with metric definitions and coverage notes."""
    with ro_conn() as conn:
        obs = [dict(r) for r in conn.execute("SELECT company, metric, period, value, unit, currency, value_type, market_definition, geography, source_name, source_url, retrieved_at, coverage_note FROM market_observations ORDER BY company, period DESC LIMIT 40")]
    for o in obs[:10]:
        ctx.deps.rec.source(f"{o['company']} {o['metric']} {o['period']}", o["source_url"], o["retrieved_at"])
    return {"observations": obs, "note": "Company revenues are not market shares and are not comparable across segments unless stated."}


@traced
def list_partner_candidates(ctx: RunContext[Deps], program_id: int | None = None) -> dict:
    """Potential license-out partners with evidence-based criteria scores (not confirmed interest)."""
    with ro_conn() as conn:
        sql = "SELECT * FROM partner_candidates" + (" WHERE program_id = ?" if program_id else "") + " ORDER BY fit_score DESC LIMIT 10"
        out = []
        for r in conn.execute(sql, (program_id,) if program_id else ()):
            ev = jload(r["evidence_json"], [])
            out.append({"company": r["company"], "fit_score": r["fit_score"], "criteria": jload(r["criteria_json"], {}), "assessment_ai": r["ai_assessment"],
                        "evidence": [{"criterion": e.get("criterion"), "fact": e.get("fact"), "url": e.get("source_url")} for e in ev][:6], "gaps": jload(r["gaps_json"], [])})
            for e in ev[:3]:
                ctx.deps.rec.source(e.get("fact", "")[:80], e.get("source_url", ""), e.get("retrieved_at"))
    return {"partners": out, "note": "Potential partners based on public evidence; not confirmed interest."}


ASSISTANT_TOOLS = [get_pipeline, list_milestones, get_budget_summary, calculate_cash_forecast, check_milestone_funding, simulate_milestone_delay,
                   compare_scenario, list_scenarios, get_competitor_events, get_regulatory_documents, get_market_observations, list_partner_candidates]
