"""Budgets, cash, FX, commitments, scenarios, summaries, and exports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ..db import get_conn, jdump, jload, log_activity, rows, set_setting, utc_now
from ..finance import calc, ledger
from ..finance.fx import describe_method
from ..finance.imports import to_csv
from ..finance.money import from_minor, to_minor
from ..schemas import (
    AccountIn, AllocationRuleIn, BalanceIn, BudgetApprove, BudgetLineIn, CommitmentIn, FxRateIn, PlannedFlowIn,
    ScenarioIn, SettingsIn, TxnPatch,
)

router = APIRouter(prefix="/api/finance", tags=["finance"])


# ------------------------------------------------------------------ settings


@router.get("/settings")
def get_fin_settings(conn=Depends(get_conn)):
    s = ledger.settings(conn)
    s["as_of"] = ledger.as_of_date(conn).isoformat()
    s["as_of_override"] = conn.execute("SELECT value FROM app_settings WHERE key = 'as_of_override'").fetchone()
    s["as_of_override"] = s["as_of_override"][0] if s["as_of_override"] else None
    return s


@router.put("/settings")
def put_fin_settings(body: SettingsIn, conn=Depends(get_conn)):
    data = body.model_dump(exclude_unset=True)
    cur = ledger.settings(conn)
    if "reporting_currency" in data and data["reporting_currency"]:
        set_setting(conn, "reporting_currency", data["reporting_currency"])
    if data.get("min_reserve") is not None:
        ccy = data.get("reporting_currency") or cur["reporting_currency"]
        set_setting(conn, "min_reserve_minor", str(to_minor(data["min_reserve"], ccy)))
    for k in ("burn_period_months", "horizon_months", "timezone", "company_name"):
        if data.get(k) is not None:
            if k == "timezone":
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

                try:
                    ZoneInfo(data[k])
                except (ZoneInfoNotFoundError, ValueError):
                    raise HTTPException(422, f"Unknown timezone {data[k]!r}")
            set_setting(conn, k, str(data[k]))
    if data.get("as_of_override"):
        set_setting(conn, "as_of_override", data["as_of_override"].isoformat())
    if data.get("clear_as_of_override"):
        conn.execute("DELETE FROM app_settings WHERE key = 'as_of_override'")
    log_activity(conn, "update", "settings", None, {"fields": sorted(data)})
    return get_fin_settings(conn)


# ---------------------------------------------------------- accounts & cash


@router.get("/accounts")
def accounts(conn=Depends(get_conn)):
    accs = rows(conn.execute("SELECT a.*, e.name AS legal_entity, e.base_currency FROM cash_accounts a LEFT JOIN legal_entities e ON e.id = a.legal_entity_id ORDER BY a.id").fetchall())
    bals = rows(conn.execute("SELECT * FROM cash_balances ORDER BY as_of_date DESC, id DESC").fetchall())
    return {"accounts": accs, "balances": bals}


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, conn=Depends(get_conn)):
    ent = conn.execute("SELECT id FROM legal_entities WHERE name = ?", (body.legal_entity,)).fetchone()
    eid = ent[0] if ent else conn.execute("INSERT INTO legal_entities (name, base_currency) VALUES (?, ?)", (body.legal_entity, body.entity_base_currency)).lastrowid
    if conn.execute("SELECT 1 FROM cash_accounts WHERE name = ?", (body.name,)).fetchone():
        raise HTTPException(409, "Account name already exists")
    aid = conn.execute("INSERT INTO cash_accounts (name, legal_entity_id, currency) VALUES (?, ?, ?)", (body.name, eid, body.currency)).lastrowid
    log_activity(conn, "create", "cash_account", aid, {"name": body.name})
    return {"id": aid}


@router.post("/balances", status_code=201)
def add_balance(body: BalanceIn, conn=Depends(get_conn)):
    acc = conn.execute("SELECT * FROM cash_accounts WHERE id = ?", (body.account_id,)).fetchone()
    if not acc:
        raise HTTPException(404, "Account not found")
    bid = conn.execute(
        "INSERT INTO cash_balances (account_id, as_of_date, balance_minor, currency, source, created_at) VALUES (?,?,?,?,?,?)",
        (body.account_id, body.as_of_date.isoformat(), to_minor(body.balance, acc["currency"]), acc["currency"], body.source, utc_now()),
    ).lastrowid
    log_activity(conn, "reconcile", "cash_balance", bid, {"account": acc["name"], "as_of": body.as_of_date.isoformat()})
    return {"id": bid}


# ------------------------------------------------------------------------ fx


@router.get("/fx")
def fx_rates(conn=Depends(get_conn)):
    return {"rates": rows(conn.execute("SELECT * FROM fx_rates ORDER BY rate_date DESC, base, quote").fetchall()), "method": describe_method()}


@router.post("/fx", status_code=201)
def add_fx(body: FxRateIn, conn=Depends(get_conn)):
    if body.base == body.quote:
        raise HTTPException(422, "Base and quote must differ")
    conn.execute(
        "INSERT INTO fx_rates (base, quote, rate, rate_date, source, method, created_at) VALUES (?,?,?,?,?, 'manual', ?) "
        "ON CONFLICT(base, quote, rate_date, source) DO UPDATE SET rate = excluded.rate",
        (body.base, body.quote, str(body.rate), body.rate_date.isoformat(), body.source, utc_now()),
    )
    log_activity(conn, "set_rate", "fx_rate", None, {"pair": f"{body.base}/{body.quote}", "date": body.rate_date.isoformat(), "source": body.source})
    return {"ok": True}


@router.post("/fx/fetch-ecb")
async def fetch_ecb(conn=Depends(get_conn)):
    from ..research.connectors.ecb import fetch_reference_rates

    try:
        result = await fetch_reference_rates()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"ECB reference rates unavailable: {type(exc).__name__}")
    n = 0
    for q, rate in result["rates"].items():
        if q not in ("USD", "HKD", "CNY"):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO fx_rates (base, quote, rate, rate_date, source, method, created_at) VALUES ('EUR', ?, ?, ?, ?, 'ecb_reference', ?)",
            (q, rate, result["date"], "ECB euro foreign exchange reference rates", utc_now()),
        )
        n += 1
    log_activity(conn, "fetch_rates", "fx_rate", None, {"source": result["url"], "date": result["date"], "count": n})
    return {"rate_date": result["date"], "source_url": result["url"], "stored": n, "retrieved_at": result["retrieved_at"]}


# -------------------------------------------------------------------- budget


def _line_out(r, sched) -> dict:
    d = dict(r)
    d["schedule"] = sched.get(r["id"], {})
    d["scheduled_total_minor"] = sum(d["schedule"].values())
    return d


@router.get("/budget-lines")
def budget_lines(program_id: int | None = None, conn=Depends(get_conn)):
    sched: dict[int, dict] = {}
    for s in conn.execute("SELECT * FROM budget_schedule ORDER BY month"):
        sched.setdefault(s["budget_line_id"], {})[s["month"]] = s["amount_minor"]
    sql = ("SELECT b.*, p.code AS program_code, m.name AS milestone_name FROM budget_lines b LEFT JOIN programs p ON p.id = b.program_id "
           "LEFT JOIN milestones m ON m.id = b.milestone_id")
    params = []
    if program_id:
        sql += " WHERE b.program_id = ?"
        params.append(program_id)
    return [_line_out(r, sched) for r in conn.execute(sql + " ORDER BY b.program_id IS NULL, b.program_id, b.milestone_id, b.id", params)]


def _validate_line_links(conn, body: BudgetLineIn):
    if body.milestone_id:
        m = conn.execute("SELECT program_id FROM milestones WHERE id = ?", (body.milestone_id,)).fetchone()
        if not m:
            raise HTTPException(422, "Milestone not found")
        if body.program_id and m["program_id"] != body.program_id:
            raise HTTPException(422, "Milestone belongs to a different program")
        return m["program_id"]
    return body.program_id


def _write_schedule(conn, line_id: int, schedule: dict, currency: str):
    conn.execute("DELETE FROM budget_schedule WHERE budget_line_id = ?", (line_id,))
    for month, amt in schedule.items():
        conn.execute("INSERT INTO budget_schedule (budget_line_id, month, amount_minor) VALUES (?,?,?)", (line_id, month, to_minor(Decimal(amt), currency)))


@router.post("/budget-lines", status_code=201)
def create_line(body: BudgetLineIn, conn=Depends(get_conn)):
    program_id = _validate_line_links(conn, body)
    now = utc_now()
    lid = conn.execute(
        "INSERT INTO budget_lines (program_id, milestone_id, category, description, currency, planned_minor, contingency_bps, owner, estimate_source, assumptions, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?, 'draft', ?, ?)",
        (program_id, body.milestone_id, body.category, body.description, body.currency, to_minor(body.planned, body.currency),
         int(body.contingency_pct * 100), body.owner, body.estimate_source, body.assumptions, now, now),
    ).lastrowid
    _write_schedule(conn, lid, body.schedule, body.currency)
    log_activity(conn, "create", "budget_line", lid, {"category": body.category, "planned_minor": to_minor(body.planned, body.currency), "currency": body.currency})
    return {"id": lid}


@router.put("/budget-lines/{lid}")
def update_line(lid: int, body: BudgetLineIn, conn=Depends(get_conn)):
    cur = conn.execute("SELECT * FROM budget_lines WHERE id = ?", (lid,)).fetchone()
    if not cur:
        raise HTTPException(404, "Budget line not found")
    if cur["status"] == "approved" and body.currency != cur["currency"]:
        raise HTTPException(409, "Currency of an approved line cannot change; create a new line.")
    program_id = _validate_line_links(conn, body)
    conn.execute(
        "UPDATE budget_lines SET program_id=?, milestone_id=?, category=?, description=?, currency=?, planned_minor=?, contingency_bps=?, owner=?, estimate_source=?, assumptions=?, updated_at=? WHERE id=?",
        (program_id, body.milestone_id, body.category, body.description, body.currency, to_minor(body.planned, body.currency), int(body.contingency_pct * 100),
         body.owner, body.estimate_source, body.assumptions, utc_now(), lid),
    )
    _write_schedule(conn, lid, body.schedule, body.currency)
    log_activity(conn, "update", "budget_line", lid, {"note": "approved amount unchanged; use approve to change it" if cur["status"] == "approved" else "draft edited"})
    return {"id": lid}


@router.post("/budget-lines/{lid}/approve")
def approve_line(lid: int, body: BudgetApprove, conn=Depends(get_conn)):
    cur = conn.execute("SELECT * FROM budget_lines WHERE id = ?", (lid,)).fetchone()
    if not cur:
        raise HTTPException(404, "Budget line not found")
    amount = to_minor(body.approved, cur["currency"])
    conn.execute("UPDATE budget_lines SET approved_minor = ?, status = 'approved', approved_at = ?, updated_at = ? WHERE id = ?", (amount, utc_now(), utc_now(), lid))
    log_activity(conn, "approve", "budget_line", lid, {"previous_approved_minor": cur["approved_minor"], "approved_minor": amount, "currency": cur["currency"], "note": body.note})
    return {"id": lid, "approved_minor": amount}


@router.delete("/budget-lines/{lid}")
def delete_line(lid: int, conn=Depends(get_conn)):
    cur = conn.execute("SELECT * FROM budget_lines WHERE id = ?", (lid,)).fetchone()
    if not cur:
        raise HTTPException(404, "Budget line not found")
    if cur["status"] != "draft":
        raise HTTPException(409, "Approved budget lines cannot be deleted; close them instead.")
    conn.execute("DELETE FROM budget_lines WHERE id = ?", (lid,))
    log_activity(conn, "delete", "budget_line", lid)
    return {"deleted": lid}


@router.post("/budget-lines/{lid}/close")
def close_line(lid: int, conn=Depends(get_conn)):
    conn.execute("UPDATE budget_lines SET status = 'closed', updated_at = ? WHERE id = ?", (utc_now(), lid))
    log_activity(conn, "close", "budget_line", lid)
    return {"id": lid}


# --------------------------------------------------------------- commitments


@router.get("/commitments")
def commitments(conn=Depends(get_conn)):
    return rows(conn.execute(
        "SELECT c.*, p.code AS program_code, m.name AS milestone_name FROM commitments c LEFT JOIN programs p ON p.id = c.program_id "
        "LEFT JOIN milestones m ON m.id = c.milestone_id ORDER BY c.status, c.expected_payment_date").fetchall())


@router.post("/commitments", status_code=201)
def create_commitment(body: CommitmentIn, conn=Depends(get_conn)):
    cid = conn.execute(
        "INSERT INTO commitments (program_id, milestone_id, category, counterparty, description, currency, amount_minor, expected_payment_date, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (body.program_id, body.milestone_id, body.category, body.counterparty, body.description, body.currency, to_minor(body.amount, body.currency),
         body.expected_payment_date.isoformat() if body.expected_payment_date else None, utc_now()),
    ).lastrowid
    log_activity(conn, "create", "commitment", cid, {"counterparty": body.counterparty})
    return {"id": cid}


@router.post("/commitments/{cid}/link-payment")
def link_payment(cid: int, transaction_id: int, conn=Depends(get_conn)):
    """Mark a commitment paid by a specific transaction, so it is counted once (as actual)."""
    c = conn.execute("SELECT * FROM commitments WHERE id = ?", (cid,)).fetchone()
    t = conn.execute("SELECT * FROM transactions WHERE id = ? AND reversed = 0", (transaction_id,)).fetchone()
    if not c or not t:
        raise HTTPException(404, "Commitment or transaction not found")
    if t["direction"] != "outflow":
        raise HTTPException(422, "Only an outflow can pay a commitment")
    conn.execute("UPDATE commitments SET status = 'paid', paid_transaction_id = ? WHERE id = ?", (transaction_id, cid))
    conn.execute("UPDATE transactions SET commitment_id = ?, program_id = COALESCE(program_id, ?), milestone_id = COALESCE(milestone_id, ?), "
                 "category = COALESCE(category, ?), allocation = CASE WHEN ? IS NOT NULL THEN 'direct' ELSE allocation END WHERE id = ?",
                 (cid, c["program_id"], c["milestone_id"], c["category"], c["program_id"], transaction_id))
    warn = None
    if t["amount_minor"] != c["amount_minor"] or t["currency"] != c["currency"]:
        warn = "Payment amount differs from the commitment; the difference is not carried forward automatically."
    log_activity(conn, "link_payment", "commitment", cid, {"transaction_id": transaction_id, "warning": warn})
    return {"ok": True, "warning": warn}


@router.post("/commitments/{cid}/cancel")
def cancel_commitment(cid: int, conn=Depends(get_conn)):
    conn.execute("UPDATE commitments SET status = 'cancelled' WHERE id = ? AND status = 'open'", (cid,))
    log_activity(conn, "cancel", "commitment", cid)
    return {"ok": True}


# -------------------------------------------------------------- planned flows


@router.get("/planned-flows")
def planned_flows(conn=Depends(get_conn)):
    return rows(conn.execute("SELECT * FROM planned_flows ORDER BY flow_date").fetchall())


@router.post("/planned-flows", status_code=201)
def create_flow(body: PlannedFlowIn, conn=Depends(get_conn)):
    fid = conn.execute(
        "INSERT INTO planned_flows (label, flow_date, amount_minor, currency, direction, kind, certainty, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (body.label, body.flow_date.isoformat(), to_minor(body.amount, body.currency), body.currency, body.direction, body.kind, body.certainty, utc_now()),
    ).lastrowid
    log_activity(conn, "create", "planned_flow", fid, {"certainty": body.certainty})
    return {"id": fid}


@router.post("/planned-flows/{fid}/confirm")
def confirm_flow(fid: int, conn=Depends(get_conn)):
    conn.execute("UPDATE planned_flows SET certainty = 'confirmed' WHERE id = ?", (fid,))
    log_activity(conn, "confirm", "planned_flow", fid)
    return {"ok": True}


@router.delete("/planned-flows/{fid}")
def delete_flow(fid: int, conn=Depends(get_conn)):
    conn.execute("DELETE FROM planned_flows WHERE id = ?", (fid,))
    log_activity(conn, "delete", "planned_flow", fid)
    return {"ok": True}


# ----------------------------------------------------------- allocation rules


@router.get("/allocation-rules")
def allocation_rules(conn=Depends(get_conn)):
    return [{**dict(r), "shares": jload(r["shares_json"], {})} for r in conn.execute("SELECT * FROM allocation_rules ORDER BY id")]


@router.post("/allocation-rules", status_code=201)
def create_rule(body: AllocationRuleIn, conn=Depends(get_conn)):
    bps = {str(k): int(v * 100) for k, v in body.shares_pct.items()}
    if sum(bps.values()) != 10000:
        raise HTTPException(422, "Shares must add up to exactly 100%")
    for pid in bps:
        if not conn.execute("SELECT 1 FROM programs WHERE id = ?", (int(pid),)).fetchone():
            raise HTTPException(422, f"Program {pid} not found")
    rid = conn.execute("INSERT INTO allocation_rules (name, category, shares_json, note, created_at) VALUES (?,?,?,?,?)",
                       (body.name, body.category, jdump(bps), body.note, utc_now())).lastrowid
    log_activity(conn, "create", "allocation_rule", rid, {"shares_bps": bps})
    return {"id": rid}


@router.post("/allocation-rules/{rid}/deactivate")
def deactivate_rule(rid: int, conn=Depends(get_conn)):
    conn.execute("UPDATE allocation_rules SET active = 0 WHERE id = ?", (rid,))
    log_activity(conn, "deactivate", "allocation_rule", rid)
    return {"ok": True}


# -------------------------------------------------------------- transactions


@router.get("/transactions")
def transactions(program_id: int | None = None, allocation: str | None = None, kind: str | None = None, batch_id: int | None = None,
                 include_reversed: bool = False, limit: int = 500, conn=Depends(get_conn)):
    sql = ("SELECT t.*, p.code AS program_code, m.name AS milestone_name, a.name AS account_name FROM transactions t "
           "LEFT JOIN programs p ON p.id = t.program_id LEFT JOIN milestones m ON m.id = t.milestone_id LEFT JOIN cash_accounts a ON a.id = t.account_id WHERE 1=1")
    params: list = []
    if not include_reversed:
        sql += " AND t.reversed = 0"
    for col, val in (("t.program_id", program_id), ("t.allocation", allocation), ("t.kind", kind), ("t.batch_id", batch_id)):
        if val is not None:
            sql += f" AND {col} = ?"
            params.append(val)
    sql += " ORDER BY t.txn_date DESC, t.id DESC LIMIT ?"
    params.append(min(max(limit, 1), 5000))
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["original"] = jload(d.pop("original_json"), {})
        out.append(d)
    return out


@router.patch("/transactions/{tid}")
def patch_txn(tid: int, body: TxnPatch, conn=Depends(get_conn)):
    t = conn.execute("SELECT * FROM transactions WHERE id = ?", (tid,)).fetchone()
    if not t:
        raise HTTPException(404, "Transaction not found")
    if t["reversed"]:
        raise HTTPException(409, "Reversed transactions cannot be edited")
    patch = body.model_dump(exclude_unset=True)
    if patch.get("milestone_id"):
        m = conn.execute("SELECT program_id FROM milestones WHERE id = ?", (patch["milestone_id"],)).fetchone()
        if not m:
            raise HTTPException(422, "Milestone not found")
        patch.setdefault("program_id", m["program_id"])
    if patch.get("program_id") and "allocation" not in patch:
        patch["allocation"] = "direct"
    if patch:
        conn.execute(f"UPDATE transactions SET {', '.join(f'{k} = ?' for k in patch)} WHERE id = ?", (*patch.values(), tid))
    log_activity(conn, "reallocate", "transaction", tid, {"before": {k: t[k] for k in patch}, "after": patch})
    return {"ok": True}


# ----------------------------------------------------------------- summaries


def _names(conn):
    progs = {r["id"]: {"code": r["code"], "name": r["name"], "origin": r["origin"]} for r in conn.execute("SELECT id, code, name, origin FROM programs")}
    ms = {r["id"]: {"name": r["name"], "program_id": r["program_id"], "planned_end": r["planned_end"], "status": r["status"]} for r in conn.execute("SELECT id, name, program_id, planned_end, status FROM milestones")}
    return progs, ms


def _pipelines(conn, by_ms: list[dict], by_prog: list[dict]) -> list[dict]:
    """Every non-archived program with all of its milestones: spent so far vs. still to spend.

    Milestones without budget lines are listed with budgeted=False rather than shown as zero.
    """
    ms_money = {m["milestone_id"]: m for m in by_ms}
    prog_money = {p["program_id"]: p for p in by_prog}
    out = []
    for p in conn.execute("SELECT id, code, name, status FROM programs WHERE archived = 0 ORDER BY code"):
        milestones = []
        for m in conn.execute("SELECT id, name, status, planned_start, planned_end FROM milestones WHERE program_id = ? AND status != 'cancelled' "
                              "ORDER BY COALESCE(planned_start, planned_end, '9999'), sort_order, id", (p["id"],)):
            mm = ms_money.get(m["id"])
            spent = mm["actual_minor"] if mm else 0
            to_spend = (mm["open_commitments_minor"] + mm["remaining_forecast_minor"]) if mm else 0
            milestones.append({"milestone_id": m["id"], "milestone": m["name"], "status": m["status"], "planned_start": m["planned_start"], "planned_end": m["planned_end"],
                               "budgeted": mm is not None, "budget_minor": (mm["approved_minor"] or mm["planned_minor"] + mm["contingency_minor"]) if mm else None,
                               "approved": bool(mm and mm["approved_minor"]), "spent_minor": spent, "committed_minor": mm["open_commitments_minor"] if mm else 0,
                               "to_spend_minor": to_spend, "total_minor": spent + to_spend})
        pm = prog_money.get(p["id"])
        # program-level lines not tied to a milestone (e.g. regulatory consulting) are shown as one extra row
        ms_total_spent = sum(x["spent_minor"] for x in milestones)
        ms_total_future = sum(x["to_spend_minor"] for x in milestones)
        if pm:
            other_spent = pm["actual_minor"] - ms_total_spent
            other_future = pm["open_commitments_minor"] + pm["remaining_forecast_minor"] - ms_total_future
            if other_spent or other_future:
                milestones.append({"milestone_id": None, "milestone": "Other program costs (not tied to a milestone)", "status": None, "planned_start": None, "planned_end": None,
                                   "budgeted": True, "budget_minor": None, "approved": False, "spent_minor": other_spent, "committed_minor": 0,
                                   "to_spend_minor": other_future, "total_minor": other_spent + other_future})
        out.append({"program_id": p["id"], "code": p["code"], "name": p["name"], "status": p["status"], "milestones": milestones,
                    "spent_minor": sum(x["spent_minor"] for x in milestones), "to_spend_minor": sum(x["to_spend_minor"] for x in milestones)})
    return out


@router.get("/summary")
def summary(burn_months: int | None = None, conn=Depends(get_conn)):
    s = ledger.summary(conn, burn_months=burn_months)
    progs, ms = _names(conn)
    bs = s["forecast"]["budget_status"]
    for b in bs["buckets"]:
        b["program"] = progs.get(b["program_id"], {}).get("code") if b["program_id"] else "Shared / company"
        b["milestone"] = ms.get(b["milestone_id"], {}).get("name") if b["milestone_id"] else None
    by_prog = calc.rollup(bs["buckets"], "program_id")
    for p in by_prog:
        p["program"] = progs.get(p["program_id"], {}).get("code") if p["program_id"] else "Shared / company"
        p["allocated_shared_minor"] = bs["shared_by_program"].get(p["program_id"], 0) if p["program_id"] else 0
    by_ms = calc.rollup([b for b in bs["buckets"] if b["milestone_id"]], "milestone_id")
    for m in by_ms:
        info = ms.get(m["milestone_id"], {})
        m["milestone"] = info.get("name")
        m["program"] = progs.get(info.get("program_id"), {}).get("code")
        m["planned_end"] = info.get("planned_end")
        m["status"] = info.get("status")
    s["budget_by_program"] = by_prog
    s["budget_by_milestone"] = by_ms
    s["pipelines"] = _pipelines(conn, by_ms, by_prog)
    s["fx_method"] = describe_method()
    s["commitments_upcoming"] = rows(conn.execute(
        "SELECT c.*, p.code AS program_code FROM commitments c LEFT JOIN programs p ON p.id = c.program_id WHERE c.status = 'open' ORDER BY c.expected_payment_date LIMIT 20").fetchall())
    return s


@router.get("/milestones/{mid}/funding")
def milestone_funding(mid: int, scenario_id: int | None = None, conn=Depends(get_conn)):
    inp, _ = ledger.forecast_inputs(conn)
    if scenario_id:
        inp = calc.apply_scenario(inp, _scenario(conn, scenario_id)["assumptions"])
    try:
        return calc.milestone_funding(mid, inp)
    except KeyError:
        raise HTTPException(404, "Milestone not found or its program is archived")


# ----------------------------------------------------------------- scenarios


def _scenario(conn, sid: int) -> dict:
    r = conn.execute("SELECT * FROM scenarios WHERE id = ?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "Scenario not found")
    d = dict(r)
    d["assumptions"] = jload(d.pop("assumptions_json"), {})
    return d


@router.get("/scenarios")
def scenarios(conn=Depends(get_conn)):
    out = []
    for r in conn.execute("SELECT * FROM scenarios ORDER BY id"):
        d = dict(r)
        d["assumptions"] = jload(d.pop("assumptions_json"), {})
        out.append(d)
    return {"scenarios": out, "templates": calc.SCENARIO_TEMPLATES}


def _validate_assumptions(conn, a: dict) -> dict:
    allowed = {"milestone_shifts", "shift_unstarted_months", "propagate_to_dependents", "category_cost_change_pct", "financing",
               "extra_monthly_cost", "include_hypothetical_planned_flows", "shift_commitments"}
    unknown = set(a) - allowed
    if unknown:
        raise HTTPException(422, f"Unknown assumption keys: {sorted(unknown)}")
    for k, v in (a.get("milestone_shifts") or {}).items():
        if not conn.execute("SELECT 1 FROM milestones WHERE id = ?", (int(k),)).fetchone():
            raise HTTPException(422, f"Milestone {k} not found")
        if not -36 <= int(v) <= 36:
            raise HTTPException(422, "Shifts must be between -36 and 36 months")
    for f in a.get("financing") or []:
        try:
            date.fromisoformat(f["date"])
            if f["currency"] not in ("USD", "HKD", "CNY"):
                raise ValueError
            if "amount" in f and "amount_minor" not in f:
                f["amount_minor"] = to_minor(Decimal(str(f.pop("amount"))), f["currency"])
            if int(f["amount_minor"]) < 0:
                raise ValueError
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "Each financing item needs date (YYYY-MM-DD), currency, and a non-negative amount")
    emc = a.get("extra_monthly_cost")
    if emc and "amount" in emc and "amount_minor" not in emc:
        emc["amount_minor"] = to_minor(Decimal(str(emc.pop("amount"))), emc.get("currency", "USD"))
    return a


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioIn, conn=Depends(get_conn)):
    a = _validate_assumptions(conn, dict(body.assumptions))
    now = utc_now()
    sid = conn.execute("INSERT INTO scenarios (name, kind, description, assumptions_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                       (body.name, body.kind, body.description, jdump(a), now, now)).lastrowid
    log_activity(conn, "create", "scenario", sid, {"name": body.name})
    return _scenario(conn, sid)


@router.put("/scenarios/{sid}")
def update_scenario(sid: int, body: ScenarioIn, conn=Depends(get_conn)):
    _scenario(conn, sid)
    a = _validate_assumptions(conn, dict(body.assumptions))
    conn.execute("UPDATE scenarios SET name=?, kind=?, description=?, assumptions_json=?, updated_at=? WHERE id=?", (body.name, body.kind, body.description, jdump(a), utc_now(), sid))
    log_activity(conn, "update", "scenario", sid)
    return _scenario(conn, sid)


@router.delete("/scenarios/{sid}")
def delete_scenario(sid: int, conn=Depends(get_conn)):
    conn.execute("DELETE FROM scenarios WHERE id = ?", (sid,))
    log_activity(conn, "delete", "scenario", sid)
    return {"ok": True}


@router.get("/scenarios/{sid}/compare")
def compare_scenario(sid: int, conn=Depends(get_conn)):
    sc = _scenario(conn, sid)
    inp, _ = ledger.forecast_inputs(conn)
    base_fc = calc.forecast(inp)
    scen_fc = calc.forecast(calc.apply_scenario(inp, sc["assumptions"]))
    return {
        "scenario": sc,
        "comparison": calc.compare(base_fc, scen_fc),
        "base_issues": base_fc["issues"],
        "scenario_issues": scen_fc["issues"],
        "currency": base_fc["currency"],
        "reserve_minor": base_fc["reserve_minor"],
        "note": "Scenario results are computed on a copy. The approved baseline, budgets and milestones are unchanged.",
    }


# -------------------------------------------------------------------- export


def _fmt(minor, ccy):
    return None if minor is None else from_minor(minor, ccy)


@router.get("/export/summary.csv", response_class=PlainTextResponse)
def export_summary(conn=Depends(get_conn)):
    s = summary(conn=conn)
    ccy = s["currency"]
    recs = [["section", "item", "value", "currency", "note"]]
    recs.append(["meta", "as_of", s["as_of"], "", "Management cash view; not audited or statutory consolidated statements"])
    recs.append(["cash", "available_cash", _fmt(s["cash"]["available_cash_minor"], ccy), ccy, "complete" if s["cash"]["complete"] else "INCOMPLETE"])
    recs.append(["burn", "gross_burn_monthly", _fmt(s["burn"]["gross_burn_monthly_minor"], ccy), ccy, f"{s['burn']['period_start']} for {s['burn']['months']} months"])
    recs.append(["burn", "net_burn_monthly", _fmt(s["burn"]["net_burn_monthly_minor"], ccy), ccy, s["definitions"]["net_burn"]])
    recs.append(["runway", "simple_runway_months", s["simple_runway"]["months"], "", s["simple_runway"]["note"]])
    recs.append(["runway", "below_reserve_month", s["forecast"]["below_reserve_month"], "", s["definitions"]["forecast_runway"]])
    for p in s["budget_by_program"]:
        for k in ("approved_minor", "actual_minor", "open_commitments_minor", "remaining_forecast_minor", "forecast_at_completion_minor"):
            recs.append(["budget_by_program", f"{p['program']}:{k.replace('_minor', '')}", _fmt(p[k], ccy), ccy, ""])
    for m in s["forecast"]["months"]:
        recs.append(["forecast", m["month"], _fmt(m["closing_minor"], ccy), ccy, f"outflows {_fmt(m['total_outflows_minor'], ccy)}; inflows {_fmt(m['inflows'], ccy)}"])
    for i in s["completeness"]:
        recs.append(["warning", i["code"], i["message"], "", i["level"]])
    for k, v in s["definitions"].items():
        recs.append(["definition", k, v, "", ""])
    recs.append(["assumption", "fx_method", s["fx_method"], "", ""])
    recs.append(["assumption", "forecast_method", s["forecast"]["method"], "", ""])
    for sc in scenarios(conn)["scenarios"]:
        recs.append(["scenario", sc["name"], jdump(sc["assumptions"]), "", sc.get("description") or ""])
    return PlainTextResponse(to_csv(recs[0], recs[1:]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=financial_summary.csv"})


@router.get("/export/transactions.csv", response_class=PlainTextResponse)
def export_txns(conn=Depends(get_conn)):
    header = ["id", "date", "amount", "currency", "direction", "kind", "counterparty", "description", "category", "program", "milestone", "allocation", "legal_entity", "account", "batch_id", "source_row", "reversed"]
    recs = []
    for t in transactions(include_reversed=True, limit=5000, conn=conn):
        recs.append([t["id"], t["txn_date"], from_minor(t["amount_minor"], t["currency"]), t["currency"], t["direction"], t["kind"], t["counterparty"], t["description"],
                     t["category"], t["program_code"], t["milestone_name"], t["allocation"], t["legal_entity"], t["account_name"], t["batch_id"], t["source_row"], t["reversed"]])
    return PlainTextResponse(to_csv(header, recs), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=transactions.csv"})
