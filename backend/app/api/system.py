"""Status, settings, activity log, agent runs, usage metrics, and demo reset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..agents.llm import pricing
from ..config import get_settings
from ..db import get_conn, get_setting, jdump, jload, log_activity, rows, set_setting
from ..schemas import CompanyIn
from ..research import cache

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status")
def status(conn=Depends(get_conn)):
    s = get_settings()
    progs = conn.execute("SELECT COUNT(*), SUM(origin = 'synthetic') FROM programs").fetchone()
    last_runs = {r["agent"]: r["started_at"] for r in conn.execute("SELECT agent, MAX(started_at) AS started_at FROM agent_runs WHERE status = 'succeeded' GROUP BY agent")}
    return {
        **s.provider_status(),
        "database": s.database_path.name,
        "workspace_label": get_setting(conn, "workspace_label", None),
        "contains_synthetic_data": bool(progs[1]),
        "as_of_override": get_setting(conn, "as_of_override"),
        "timezone": get_setting(conn, "timezone", s.default_timezone),
        "scheduler": {"enabled_in_app": s.enable_scheduler and not s.is_demo, "briefing_hour_local": s.briefing_hour,
                      "note": "Automatic refresh runs only while this app (or the scheduled daily-job command) is running on a computer that is awake."},
        "last_successful_runs": last_runs,
        "limits": {"per_run_requests": s.run_request_limit, "per_run_tool_calls": s.run_tool_calls_limit, "per_run_total_tokens": s.run_total_tokens_limit,
                   "per_run_timeout_s": s.run_timeout_seconds, "daily_runs": s.daily_run_limit, "daily_tokens": s.daily_token_limit, "daily_cost_usd": s.daily_cost_limit_usd,
                   "upload_max_bytes": s.upload_max_bytes, "import_max_rows": s.import_max_rows, "http_concurrency": s.http_concurrency, "http_retries": s.http_retries,
                   "research_cache_ttl_hours": s.research_cache_ttl_hours},
        "access_boundary": "Local prototype: the API listens on 127.0.0.1 only and has no user accounts. Anyone with access to this computer account can use it. See docs/SECURITY.md before sharing.",
    }


DEFAULT_VALUES = ["All life matters"]


@router.get("/settings/company")
def get_company(conn=Depends(get_conn)):
    """Mission and values shown at the top of the Overview. Mission is empty until the team writes it."""
    return {"mission": get_setting(conn, "company_mission", "") or "", "values": jload(get_setting(conn, "company_values"), DEFAULT_VALUES),
            "name": get_setting(conn, "company_name", "") or ""}


@router.put("/settings/company")
def put_company(body: CompanyIn, conn=Depends(get_conn)):
    set_setting(conn, "company_mission", body.mission.strip())
    set_setting(conn, "company_values", jdump([v.strip() for v in body.values if v.strip()] or DEFAULT_VALUES))
    log_activity(conn, "update", "settings", "company", {"fields": ["mission", "values"]})
    return get_company(conn)


@router.put("/settings/confidential-terms")
def set_confidential_terms(terms: str, conn=Depends(get_conn)):
    if len(terms) > 2000:
        raise HTTPException(422, "Too long")
    set_setting(conn, "confidential_terms", terms)
    return {"ok": True}


@router.get("/settings/confidential-terms")
def get_confidential_terms(conn=Depends(get_conn)):
    return {"terms": get_setting(conn, "confidential_terms", "")}


@router.get("/activity")
def activity(limit: int = 100, entity_type: str | None = None, conn=Depends(get_conn)):
    sql = "SELECT * FROM activity_log"
    params: list = []
    if entity_type:
        sql += " WHERE entity_type = ?"
        params.append(entity_type)
    out = []
    for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, min(limit, 1000))):
        d = dict(r)
        d["detail"] = jload(d.pop("detail_json"), {})
        out.append(d)
    return out


@router.get("/agent-runs")
def agent_runs(limit: int = 50, agent: str | None = None, conn=Depends(get_conn)):
    sql = "SELECT * FROM agent_runs"
    params: list = []
    if agent:
        sql += " WHERE agent = ?"
        params.append(agent)
    out = []
    for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, min(limit, 500))):
        d = dict(r)
        d["trace"] = jload(d.pop("trace_json"), [])
        d["sources"] = jload(d.pop("sources_json"), [])
        out.append(d)
    return out


@router.get("/metrics")
def metrics(days: int = 30, conn=Depends(get_conn)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    by_agent = rows(conn.execute(
        "SELECT agent, mode, COUNT(*) AS runs, SUM(status = 'succeeded') AS succeeded, SUM(status != 'succeeded') AS not_succeeded, "
        "SUM(input_tokens) AS input_tokens, SUM(cached_input_tokens) AS cached_input_tokens, SUM(output_tokens) AS output_tokens, SUM(tool_calls) AS tool_calls, "
        "AVG(duration_ms) AS avg_ms, SUM(app_cache_hits) AS cache_hits, SUM(app_cache_misses) AS cache_misses, "
        "SUM(gateway_cache_hits) AS gateway_hits, SUM(gateway_cache_misses) AS gateway_misses, SUM(quarantined_items) AS quarantined, "
        "SUM(CAST(cost_usd AS REAL)) AS cost_usd, SUM(cost_usd IS NULL AND mode = 'live') AS runs_cost_unknown "
        "FROM agent_runs WHERE started_at >= ? GROUP BY agent, mode ORDER BY agent", (since,)).fetchall())
    p = pricing()
    return {"since": since, "by_agent": by_agent, "pricing": p, "public_cache": cache.stats_summary(),
            "notes": ["Token counts are provider-reported. Demo-mode runs have no tokens and are never simulated.",
                      "Costs are estimates from the dated pricing table; unknown when a price is missing.",
                      "App cache hits = public retrieval reused from the shared cache. Gateway cache hits = Portkey replayed an earlier identical model response (costed at $0; billing unverified). Cached input tokens = provider-side prompt caching. They are different things."]}


@router.post("/demo/reset")
def demo_reset():
    s = get_settings()
    if not s.is_demo:
        raise HTTPException(403, "Reset is only available in demo mode.")
    from ..demo.seed import reset_demo_db

    reset_demo_db()
    return {"ok": True}
