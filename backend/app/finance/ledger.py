"""Load database records into calculation inputs and assemble summaries."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal

from ..db import get_setting, jload
from . import calc
from .fx import FxTable, Rate

DEFAULTS = {
    "reporting_currency": "USD",
    "min_reserve_minor": "0",
    "burn_period_months": "3",
    "horizon_months": "18",
    "timezone": None,  # filled from config
    "company_name": "",
}


def settings(conn: sqlite3.Connection) -> dict:
    from ..config import get_settings

    out = {}
    for k, v in DEFAULTS.items():
        out[k] = get_setting(conn, k, v if v is not None else get_settings().default_timezone)
    out["min_reserve_minor"] = int(out["min_reserve_minor"] or 0)
    out["burn_period_months"] = int(out["burn_period_months"] or 3)
    out["horizon_months"] = int(out["horizon_months"] or 18)
    return out


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def fx_table(conn: sqlite3.Connection) -> FxTable:
    rates = [
        Rate(r["base"], r["quote"], Decimal(r["rate"]), date.fromisoformat(r["rate_date"]), r["source"], r["method"])
        for r in conn.execute("SELECT * FROM fx_rates")
    ]
    return FxTable(rates)


def load_txns(conn: sqlite3.Connection) -> list[calc.Txn]:
    return [
        calc.Txn(
            id=r["id"], txn_date=date.fromisoformat(r["txn_date"]), amount_minor=r["amount_minor"], currency=r["currency"],
            direction=r["direction"], kind=r["kind"], category=r["category"], program_id=r["program_id"],
            milestone_id=r["milestone_id"], allocation=r["allocation"], legal_entity=r["legal_entity"],
            account_id=r["account_id"], commitment_id=r["commitment_id"], reversed=bool(r["reversed"]),
        )
        for r in conn.execute("SELECT * FROM transactions")
    ]


def load_accounts(conn):
    return [
        calc.Account(r["id"], r["name"], r["currency"], r["entity"], bool(r["active"]))
        for r in conn.execute("SELECT a.*, e.name AS entity FROM cash_accounts a LEFT JOIN legal_entities e ON e.id = a.legal_entity_id")
    ]


def load_balances(conn):
    return [calc.Balance(r["account_id"], date.fromisoformat(r["as_of_date"]), r["balance_minor"], r["currency"]) for r in conn.execute("SELECT * FROM cash_balances")]


def load_lines(conn, include_archived_programs: bool = False):
    sched: dict[int, dict[str, int]] = {}
    for r in conn.execute("SELECT * FROM budget_schedule"):
        sched.setdefault(r["budget_line_id"], {})[r["month"]] = r["amount_minor"]
    q = "SELECT b.* FROM budget_lines b LEFT JOIN programs p ON p.id = b.program_id"
    if not include_archived_programs:
        q += " WHERE p.id IS NULL OR p.archived = 0"
    return [
        calc.BudgetLine(r["id"], r["program_id"], r["milestone_id"], r["category"], r["currency"], r["planned_minor"],
                        r["approved_minor"], r["contingency_bps"], r["status"], sched.get(r["id"], {}))
        for r in conn.execute(q)
    ]


def load_milestones(conn):
    return [
        calc.Milestone(r["id"], r["program_id"], r["name"], _d(r["planned_start"]), _d(r["planned_end"]), r["status"], [int(x) for x in jload(r["depends_on_json"], [])])
        for r in conn.execute("SELECT m.* FROM milestones m JOIN programs p ON p.id = m.program_id WHERE p.archived = 0")
    ]


def load_commitments(conn):
    return [
        calc.Commitment(r["id"], r["program_id"], r["milestone_id"], r["category"], r["currency"], r["amount_minor"], _d(r["expected_payment_date"]), r["status"], r["counterparty"])
        for r in conn.execute("SELECT * FROM commitments")
    ]


def load_flows(conn):
    return [
        calc.PlannedFlow(r["label"], date.fromisoformat(r["flow_date"]), r["amount_minor"], r["currency"], r["direction"], r["kind"], r["certainty"])
        for r in conn.execute("SELECT * FROM planned_flows")
    ]


def load_rules(conn):
    return [
        calc.AllocationRule(r["id"], r["name"], r["category"], {int(k): int(v) for k, v in jload(r["shares_json"], {}).items()})
        for r in conn.execute("SELECT * FROM allocation_rules WHERE active = 1")
    ]


def as_of_date(conn) -> date:
    override = get_setting(conn, "as_of_override")
    return date.fromisoformat(override) if override else date.today()


def forecast_inputs(conn: sqlite3.Connection, as_of: date | None = None) -> tuple[calc.ForecastInputs, dict]:
    s = settings(conn)
    as_of = as_of or as_of_date(conn)
    fx = fx_table(conn)
    txns = load_txns(conn)
    cash = calc.cash_position(load_accounts(conn), load_balances(conn), txns, as_of, fx, s["reporting_currency"])
    inp = calc.ForecastInputs(
        as_of=as_of, reporting=s["reporting_currency"], fx=fx,
        start_cash_minor=cash["available_cash_minor"] if cash["complete"] else None,
        reserve_minor=s["min_reserve_minor"], horizon_months=s["horizon_months"],
        lines=load_lines(conn), milestones=load_milestones(conn), txns=txns,
        commitments=load_commitments(conn), planned_flows=load_flows(conn), rules=load_rules(conn),
    )
    return inp, cash


def burn_window(as_of: date, months: int) -> date:
    """The last `months` full calendar months before the as-of month."""
    first_this_month = date(as_of.year, as_of.month, 1)
    return calc.add_months(first_this_month, -months)


def summary(conn: sqlite3.Connection, as_of: date | None = None, burn_months: int | None = None) -> dict:
    inp, cash = forecast_inputs(conn, as_of)
    s = settings(conn)
    months = burn_months or s["burn_period_months"]
    b = calc.burn(inp.txns, burn_window(inp.as_of, months), months, inp.fx, inp.reporting)
    runway = calc.simple_runway(inp.start_cash_minor, b["net_burn_monthly_minor"])
    fc = calc.forecast(inp)
    completeness = completeness_checks(conn, cash, b, fc)
    return {
        "as_of": inp.as_of.isoformat(),
        "currency": inp.reporting,
        "settings": s,
        "cash": cash,
        "burn": b,
        "simple_runway": runway,
        "forecast": fc,
        "completeness": completeness,
        "definitions": DEFINITIONS,
    }


DEFINITIONS = {
    "gross_burn": "Operating cash outflows over the selected period divided by the number of months.",
    "net_burn": "Operating cash outflows minus operating cash inflows (including refunds) over the period, divided by the number of months. Financing inflows and transfers between company accounts are excluded.",
    "simple_runway": "Available reconciled cash divided by positive average monthly net burn. Not shown when net burn is zero or negative.",
    "forecast_runway": "The first month in which projected month-end cash falls below the minimum reserve (and below zero), based on dated future budget schedules, open commitments, and confirmed planned flows.",
    "available_cash": "Latest reconciled balance per account plus later transactions on that account. Imported transactions alone never establish a balance.",
    "scope": "Management cash view across the legal entities you entered. This is not an audited or statutory consolidated financial statement.",
}


def completeness_checks(conn, cash, burn_res, fc) -> list[dict]:
    out = []
    for i in cash["issues"]:
        out.append({**i, "area": "cash"})
    for i in burn_res["issues"]:
        out.append({**i, "area": "burn"})
    for i in fc["issues"]:
        out.append({**i, "area": "forecast"})
    n_unalloc = conn.execute("SELECT COUNT(*) FROM transactions WHERE reversed = 0 AND allocation = 'unallocated' AND kind IN ('operating','refund') AND direction = 'outflow'").fetchone()[0]
    if n_unalloc:
        out.append({"level": "warning", "code": "unallocated_spend", "message": f"{n_unalloc} operating payment(s) are not allocated to a program or shared pool.", "area": "allocation"})
    no_budget = conn.execute(
        "SELECT COUNT(*) FROM milestones m JOIN programs p ON p.id = m.program_id WHERE p.archived = 0 AND m.status NOT IN ('done','cancelled') "
        "AND NOT EXISTS (SELECT 1 FROM budget_lines b WHERE b.milestone_id = m.id)"
    ).fetchone()[0]
    if no_budget:
        out.append({"level": "warning", "code": "milestones_without_budget", "message": f"{no_budget} open milestone(s) have no budget lines, so the forecast understates future costs.", "area": "budget"})
    if not conn.execute("SELECT 1 FROM fx_rates LIMIT 1").fetchone():
        out.append({"level": "warning", "code": "no_fx_rates", "message": "No exchange rates recorded; non-reporting-currency amounts cannot be converted.", "area": "fx"})
    seen, dedup = set(), []
    stale_pairs: list[str] = []
    for i in out:
        if i["code"] == "stale_fx":  # one combined message listing each currency/rate date once
            for pair in i["message"].split(": ", 1)[-1].rstrip(".").split(", "):
                if pair not in stale_pairs:
                    stale_pairs.append(pair)
            continue
        if (i["code"], i["message"]) not in seen:
            seen.add((i["code"], i["message"]))
            dedup.append(i)
    if stale_pairs:
        dedup.append({"level": "warning", "code": "stale_fx", "area": "fx",
                      "message": "Some conversions used exchange rates older than 10 days: " + ", ".join(sorted(stale_pairs)) + "."})
    return dedup
