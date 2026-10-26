"""Pipeline programs and milestones."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_conn, jdump, jload, log_activity, row, rows, utc_now
from ..finance import calc, ledger
from .. import phases
from ..schemas import HUMAN_STAGES, JURISDICTIONS, VET_STAGES, MilestoneIn, MilestonePatch, ProgramIn, ProgramPatch

router = APIRouter(prefix="/api", tags=["pipelines"])

JSON_FIELDS = {"species": "species_json", "jurisdictions": "jurisdictions_json", "key_dates": "key_dates_json", "public_keywords": "public_keywords_json"}


def program_out(r: sqlite3.Row | dict) -> dict:
    d = dict(r)
    for api_name, col in JSON_FIELDS.items():
        d[api_name] = jload(d.pop(col, None), [])
    d["archived"] = bool(d["archived"])
    return d


def milestone_out(r) -> dict:
    d = dict(r)
    d["depends_on"] = jload(d.pop("depends_on_json"), [])
    d["is_decision_point"] = bool(d["is_decision_point"])
    today = date.today().isoformat()
    d["overdue"] = bool(d["planned_end"] and d["planned_end"] < today and d["status"] not in ("done", "cancelled"))
    d["baseline_slip_days"] = (
        (date.fromisoformat(d["planned_end"]) - date.fromisoformat(d["baseline_end"])).days
        if d.get("planned_end") and d.get("baseline_end") else None
    )
    return d


def get_program_or_404(conn, pid: int) -> dict:
    r = conn.execute("SELECT * FROM programs WHERE id = ?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "Program not found")
    return program_out(r)


@router.get("/reference")
def reference():
    return {"vet_stages": VET_STAGES, "human_stages": HUMAN_STAGES, "jurisdictions": JURISDICTIONS,
            "categories": ["Research", "Preclinical studies", "Manufacturing / CMC", "Analytical work", "Regulatory", "Clinical / field studies", "CRO services", "Personnel", "Facilities", "Overhead"],
            "currencies": ["USD", "HKD", "CNY"]}


@router.get("/programs")
def list_programs(
    q: str | None = None,
    use_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    include_archived: bool = False,
    conn=Depends(get_conn),
):
    sql = "SELECT * FROM programs WHERE 1=1"
    params: list = []
    if not include_archived:
        sql += " AND archived = 0"
    if q:
        sql += " AND (name LIKE ? OR code LIKE ? OR indication LIKE ? OR description LIKE ? OR species_json LIKE ?)"
        like = f"%{q}%"
        params += [like] * 5
    for col, val in (("use_type", use_type), ("status", status), ("priority", priority)):
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY archived, CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, code"
    progs = [program_out(r) for r in conn.execute(sql, params)]
    counts = {r["program_id"]: dict(r) for r in conn.execute(
        "SELECT program_id, COUNT(*) AS n, SUM(status NOT IN ('done','cancelled')) AS open_n, "
        "SUM(planned_end < date('now') AND status NOT IN ('done','cancelled')) AS overdue_n FROM milestones GROUP BY program_id")}
    for p in progs:
        c = counts.get(p["id"], {})
        p["milestone_count"] = c.get("n", 0)
        p["open_milestones"] = c.get("open_n", 0) or 0
        p["overdue_milestones"] = c.get("overdue_n", 0) or 0
    return progs


@router.post("/programs", status_code=201)
def create_program(body: ProgramIn, conn=Depends(get_conn)):
    if conn.execute("SELECT 1 FROM programs WHERE code = ?", (body.code,)).fetchone():
        raise HTTPException(409, f"Program code {body.code} already exists")
    now = utc_now()
    data = body.model_dump()
    cur = conn.execute(
        "INSERT INTO programs (code, name, description, therapeutic_area, indication, use_type, species_json, target, mechanism, modality, "
        "molecule_category, route, stage_template, stage, status, owner, priority, jurisdictions_json, key_dates_json, risks, notes, public_keywords_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["code"], data["name"], data["description"], data["therapeutic_area"], data["indication"], data["use_type"], jdump(data["species"]),
         data["target"], data["mechanism"], data["modality"], data["molecule_category"], data["route"], data["stage_template"], data["stage"],
         data["status"], data["owner"], data["priority"], jdump(data["jurisdictions"]), jdump(data["key_dates"]), data["risks"], data["notes"],
         jdump(data["public_keywords"]), now, now),
    )
    log_activity(conn, "create", "program", cur.lastrowid, {"code": body.code})
    return get_program_or_404(conn, cur.lastrowid)


def apply_program_patch(conn, pid: int, patch: dict, action: str = "update") -> dict:
    get_program_or_404(conn, pid)
    if not patch:
        return get_program_or_404(conn, pid)
    sets, params = [], []
    for k, v in patch.items():
        col = JSON_FIELDS.get(k, k)
        sets.append(f"{col} = ?")
        params.append(jdump(v) if k in JSON_FIELDS else v)
    sets.append("updated_at = ?")
    params.append(utc_now())
    conn.execute(f"UPDATE programs SET {', '.join(sets)} WHERE id = ?", (*params, pid))
    log_activity(conn, action, "program", pid, {"fields": sorted(patch)})
    return get_program_or_404(conn, pid)


@router.get("/programs/{pid}")
def get_program(pid: int, conn=Depends(get_conn)):
    p = get_program_or_404(conn, pid)
    p["milestones"] = [milestone_out(r) for r in conn.execute("SELECT * FROM milestones WHERE program_id = ? ORDER BY sort_order, planned_start, id", (pid,))]
    p["proposals"] = [
        {**dict(r), "proposal": jload(r["proposal_json"], {})}
        for r in conn.execute("SELECT id, status, created_at, decided_at, proposal_json, agent_run_id FROM classification_proposals WHERE program_id = ? ORDER BY id DESC LIMIT 5", (pid,))
    ]
    for pr in p["proposals"]:
        pr.pop("proposal_json", None)
    return p


@router.patch("/programs/{pid}")
def update_program(pid: int, body: ProgramPatch, conn=Depends(get_conn)):
    patch = body.model_dump(exclude_unset=True)
    if "key_dates" in patch:
        patch["key_dates"] = [{"label": k["label"], "date": k["date"].isoformat()} for k in patch["key_dates"]]
    if patch.get("code") and conn.execute("SELECT 1 FROM programs WHERE code = ? AND id != ?", (patch["code"], pid)).fetchone():
        raise HTTPException(409, "Program code already exists")
    return apply_program_patch(conn, pid, patch)


@router.post("/programs/{pid}/archive")
def archive_program(pid: int, archived: bool = True, conn=Depends(get_conn)):
    get_program_or_404(conn, pid)
    conn.execute("UPDATE programs SET archived = ?, updated_at = ? WHERE id = ?", (1 if archived else 0, utc_now(), pid))
    log_activity(conn, "archive" if archived else "unarchive", "program", pid)
    return get_program_or_404(conn, pid)


# ---------------------------------------------------------------- milestones


def _check_deps(conn, pid: int, mid: int | None, deps: list[int]) -> None:
    if not deps:
        return
    ids = {r[0] for r in conn.execute("SELECT id FROM milestones WHERE program_id = ?", (pid,))}
    bad = [d for d in deps if d not in ids or d == mid]
    if bad:
        raise HTTPException(422, f"Dependencies must be other milestones of the same program: {bad}")
    if mid is not None:
        graph = {r["id"]: jload(r["depends_on_json"], []) for r in conn.execute("SELECT id, depends_on_json FROM milestones WHERE program_id = ?", (pid,))}
        graph[mid] = deps
        stack, seen = list(deps), set()
        while stack:
            cur = stack.pop()
            if cur == mid:
                raise HTTPException(422, "Dependency cycle detected")
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(graph.get(cur, []))


@router.post("/programs/{pid}/milestones", status_code=201)
def create_milestone(pid: int, body: MilestoneIn, conn=Depends(get_conn)):
    get_program_or_404(conn, pid)
    _check_deps(conn, pid, None, body.depends_on)
    if body.planned_start and body.planned_end and body.planned_end < body.planned_start:
        raise HTTPException(422, "Planned end is before planned start")
    now = utc_now()
    ps = body.planned_start.isoformat() if body.planned_start else None
    pe = body.planned_end.isoformat() if body.planned_end else None
    cur = conn.execute(
        "INSERT INTO milestones (program_id, name, description, stage, planned_start, planned_end, baseline_start, baseline_end, actual_end, status, owner, "
        "is_decision_point, depends_on_json, notes, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, body.name, body.description, body.stage, ps, pe, ps if body.set_baseline else None, pe if body.set_baseline else None,
         body.actual_end.isoformat() if body.actual_end else None, body.status, body.owner, int(body.is_decision_point), jdump(body.depends_on), body.notes, body.sort_order, now, now),
    )
    log_activity(conn, "create", "milestone", cur.lastrowid, {"program_id": pid, "name": body.name, "baseline_set": body.set_baseline})
    return milestone_out(conn.execute("SELECT * FROM milestones WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.patch("/milestones/{mid}")
def update_milestone(mid: int, body: MilestonePatch, conn=Depends(get_conn)):
    m = conn.execute("SELECT * FROM milestones WHERE id = ?", (mid,)).fetchone()
    if not m:
        raise HTTPException(404, "Milestone not found")
    patch = body.model_dump(exclude_unset=True)
    set_baseline = patch.pop("set_baseline", False)
    if "depends_on" in patch:
        _check_deps(conn, m["program_id"], mid, patch["depends_on"])
        patch["depends_on_json"] = jdump(patch.pop("depends_on"))
    for k in ("planned_start", "planned_end", "actual_end"):
        if k in patch and patch[k] is not None:
            patch[k] = patch[k].isoformat()
    if "is_decision_point" in patch:
        patch["is_decision_point"] = int(bool(patch["is_decision_point"]))
    if set_baseline:
        # Baseline changes are explicit user actions, logged separately.
        patch["baseline_start"] = patch.get("planned_start", m["planned_start"])
        patch["baseline_end"] = patch.get("planned_end", m["planned_end"])
    if patch:
        sets = ", ".join(f"{k} = ?" for k in patch) + ", updated_at = ?"
        conn.execute(f"UPDATE milestones SET {sets} WHERE id = ?", (*patch.values(), utc_now(), mid))
    log_activity(conn, "set_baseline" if set_baseline else "update", "milestone", mid, {"fields": sorted(patch)})
    return milestone_out(conn.execute("SELECT * FROM milestones WHERE id = ?", (mid,)).fetchone())


@router.delete("/milestones/{mid}")
def delete_milestone(mid: int, conn=Depends(get_conn)):
    m = conn.execute("SELECT * FROM milestones WHERE id = ?", (mid,)).fetchone()
    if not m:
        raise HTTPException(404, "Milestone not found")
    linked = conn.execute(
        "SELECT (SELECT COUNT(*) FROM budget_lines WHERE milestone_id = ?) + (SELECT COUNT(*) FROM transactions WHERE milestone_id = ? AND reversed = 0) + (SELECT COUNT(*) FROM commitments WHERE milestone_id = ?)",
        (mid, mid, mid)).fetchone()[0]
    if linked:
        raise HTTPException(409, "Milestone has budgets, transactions, or commitments; set status to 'cancelled' instead of deleting.")
    conn.execute("DELETE FROM milestones WHERE id = ?", (mid,))
    log_activity(conn, "delete", "milestone", mid, {"name": m["name"]})
    return {"deleted": mid}


@router.get("/timeline")
def timeline(conn=Depends(get_conn), program_id: int | None = Query(default=None)):
    """Milestones across programs with overdue flags, decisions, dependencies, and funding status."""
    sql = "SELECT m.*, p.code AS program_code, p.name AS program_name FROM milestones m JOIN programs p ON p.id = m.program_id WHERE p.archived = 0"
    params = []
    if program_id:
        sql += " AND p.id = ?"
        params.append(program_id)
    ms = [milestone_out(r) | {"program_code": r["program_code"], "program_name": r["program_name"]} for r in conn.execute(sql + " ORDER BY planned_start IS NULL, planned_start, id", params)]
    inp, _cash = ledger.forecast_inputs(conn)
    fc = calc.forecast(inp)
    by_ms = {}
    for bk in fc["budget_status"]["buckets"]:
        if bk["milestone_id"] is not None:
            agg = by_ms.setdefault(bk["milestone_id"], {"remaining_minor": 0, "actual_minor": 0, "approved_minor": 0, "open_commitments_minor": 0})
            agg["remaining_minor"] += bk["remaining_forecast_minor"]
            agg["actual_minor"] += bk["actual_minor"]
            agg["approved_minor"] += bk["approved_minor"]
            agg["open_commitments_minor"] += bk["open_commitments_minor"]
    for m in ms:
        m["budget"] = by_ms.get(m["id"])
        if m["status"] not in ("done", "cancelled") and m["planned_end"]:
            try:
                f = calc.milestone_funding(m["id"], inp, fc)
                m["funding"] = {"funded": f["funded"], "gap_minor": f["funding_gap_minor"], "gaps": f["gaps"]}
            except KeyError:
                m["funding"] = None
    today = date.today().isoformat()
    upcoming_decisions = [m for m in ms if m["is_decision_point"] and m["status"] not in ("done", "cancelled") and (m["planned_end"] or "") >= today]
    return {"currency": fc["currency"], "milestones": ms, "upcoming_decisions": upcoming_decisions[:10], "below_reserve_month": fc["below_reserve_month"], "as_of": fc["as_of"]}


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: int, conn=Depends(get_conn)):
    r = row(conn.execute("SELECT * FROM classification_proposals WHERE id = ?", (proposal_id,)).fetchone())
    if not r:
        raise HTTPException(404, "Proposal not found")
    r["proposal"] = jload(r.pop("proposal_json"), {})
    return r


@router.get("/phase-map")
def phase_map(conn=Depends(get_conn)):
    """Pipelines (rows) x development phases (columns), with value-inflection gates; see app/phases.py."""
    progs = [dict(r) for r in conn.execute("SELECT id, code, name, status, stage FROM programs WHERE archived = 0 ORDER BY code")]
    ms = [dict(r) for r in conn.execute("SELECT id, program_id, name, stage, status, planned_start, planned_end, is_decision_point FROM milestones ORDER BY planned_start IS NULL, planned_start, id")]
    for m in ms:
        m["is_decision_point"] = bool(m["is_decision_point"])
    return phases.phase_map(progs, ms)


__all__ = ["router", "program_out", "milestone_out", "apply_program_patch", "rows"]
