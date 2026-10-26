"""Deterministic financial calculations.

Everything here is a pure function over plain dataclasses so it can be tested
without a database or a model. The LLM never computes these numbers; the
Planning Assistant calls these functions through typed tools.

Definitions (also shown in the UI):
- Gross operating burn = operating cash outflows in the period / number of months.
- Net operating burn  = (operating outflows - operating inflows incl. refunds) / months.
- Simple runway       = available cash / average monthly net burn (only if net burn > 0).
- Forecast runway     = first month in which projected month-end cash falls below
                        the minimum reserve (and separately below zero), using
                        dated future flows.
Financing inflows and transfers between company accounts are excluded from burn.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .fx import FxTable, MissingRate

# --------------------------------------------------------------------- dates


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_month(key: str) -> date:
    y, m = key.split("-")[:2]
    return date(int(y), int(m), 1)


def add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    y, m = divmod(idx, 12)
    day = min(d.day, _days_in_month(y, m + 1))
    return date(y, m + 1, day)


def _days_in_month(y: int, m: int) -> int:
    nxt = date(y + (m // 12), (m % 12) + 1, 1)
    return (nxt - date(y, m, 1)).days


def months_between(a: str, b: str) -> list[str]:
    """Inclusive list of YYYY-MM keys from a to b."""
    out, cur, end = [], parse_month(a), parse_month(b)
    while cur <= end:
        out.append(month_key(cur))
        cur = add_months(cur, 1)
    return out


# ---------------------------------------------------------------- data types


@dataclass
class Txn:
    id: int
    txn_date: date
    amount_minor: int
    currency: str
    direction: str  # outflow | inflow
    kind: str = "operating"  # operating | refund | financing | transfer
    category: str | None = None
    program_id: int | None = None
    milestone_id: int | None = None
    allocation: str = "unallocated"  # direct | shared | unallocated
    legal_entity: str | None = None
    account_id: int | None = None
    commitment_id: int | None = None
    reversed: bool = False


@dataclass
class Account:
    id: int
    name: str
    currency: str
    legal_entity: str | None = None
    active: bool = True


@dataclass
class Balance:
    account_id: int
    as_of: date
    balance_minor: int
    currency: str


@dataclass
class BudgetLine:
    id: int
    program_id: int | None
    milestone_id: int | None
    category: str
    currency: str
    planned_minor: int
    approved_minor: int | None = None
    contingency_bps: int = 0
    status: str = "draft"
    schedule: dict[str, int] = field(default_factory=dict)  # YYYY-MM -> minor


@dataclass
class Milestone:
    id: int
    program_id: int
    name: str
    planned_start: date | None = None
    planned_end: date | None = None
    status: str = "planned"
    depends_on: list[int] = field(default_factory=list)


@dataclass
class Commitment:
    id: int
    program_id: int | None
    milestone_id: int | None
    category: str | None
    currency: str
    amount_minor: int
    expected_date: date | None
    status: str = "open"
    counterparty: str = ""


@dataclass
class PlannedFlow:
    label: str
    flow_date: date
    amount_minor: int
    currency: str
    direction: str
    kind: str = "operating"
    certainty: str = "confirmed"  # confirmed | hypothetical


@dataclass
class AllocationRule:
    id: int
    name: str
    category: str | None
    shares_bps: dict[int, int]


@dataclass
class Issue:
    level: str  # warning | error | info
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


def _div_round(total: int, months: int) -> int:
    return int((Decimal(total) / Decimal(months)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class _Converter:
    """Converts to the reporting currency and remembers what could not be converted."""

    def __init__(self, fx: FxTable, reporting: str):
        self.fx, self.reporting = fx, reporting
        self.missing: list[dict] = []
        self.stale: set[tuple[str, str]] = set()

    def __call__(self, minor: int, currency: str, on: date, ref: str) -> int | None:
        try:
            c = self.fx.convert(minor, currency, self.reporting, on)
        except MissingRate as exc:
            self.missing.append({"ref": ref, "currency": currency, "amount_minor": minor, "date": on.isoformat(), "reason": str(exc)})
            return None
        if c.stale:
            self.stale.add((currency, c.rate_date.isoformat() if c.rate_date else ""))
        return c.amount_minor

    def issues(self) -> list[Issue]:
        out = []
        if self.missing:
            out.append(Issue("error", "missing_fx", f"{len(self.missing)} amount(s) could not be converted to {self.reporting} and are excluded from totals. Add exchange rates."))
        if self.stale:
            pairs = ", ".join(sorted(f"{c} (rate {d})" for c, d in self.stale))
            out.append(Issue("warning", "stale_fx", f"Some conversions used rates older than {self.fx.stale_days} days: {pairs}."))
        return out


# ---------------------------------------------------------------------- cash


def cash_position(
    accounts: list[Account],
    balances: list[Balance],
    txns: list[Txn],
    as_of: date,
    fx: FxTable,
    reporting: str,
    reconciliation_stale_days: int = 45,
) -> dict:
    """Available cash = latest reconciled balance per account + later transactions.

    Transactions never create a balance by themselves: an account without a
    reconciled balance makes the company cash total incomplete.
    """
    conv = _Converter(fx, reporting)
    issues: list[Issue] = []
    per_account = []
    total = 0
    any_balance = False
    complete = True
    for acc in accounts:
        if not acc.active:
            continue
        candidates = [b for b in balances if b.account_id == acc.id and b.as_of <= as_of]
        if not candidates:
            complete = False
            per_account.append({"account_id": acc.id, "account": acc.name, "currency": acc.currency, "status": "missing_balance"})
            issues.append(Issue("error", "missing_balance", f"Account '{acc.name}' has no reconciled opening balance on or before {as_of}; cash is incomplete."))
            continue
        bal = max(candidates, key=lambda b: b.as_of)
        if bal.currency != acc.currency:
            issues.append(Issue("error", "balance_currency", f"Balance for '{acc.name}' is in {bal.currency} but the account is {acc.currency}."))
            complete = False
            continue
        movement = 0
        skipped = 0
        applied = 0
        for t in txns:
            if t.reversed or t.account_id != acc.id or not (bal.as_of < t.txn_date <= as_of):
                continue
            if t.currency != acc.currency:
                skipped += 1
                continue
            movement += t.amount_minor if t.direction == "inflow" else -t.amount_minor
            applied += 1
        if skipped:
            issues.append(Issue("warning", "txn_currency_mismatch", f"{skipped} transaction(s) on '{acc.name}' are not in the account currency and were not applied."))
        native = bal.balance_minor + movement
        converted = conv(native, acc.currency, as_of, f"account:{acc.id}")
        age = (as_of - bal.as_of).days
        if age > reconciliation_stale_days:
            issues.append(Issue("warning", "stale_reconciliation", f"'{acc.name}' was last reconciled {age} days ago ({bal.as_of})."))
        any_balance = True
        if converted is None:
            complete = False
        else:
            total += converted
        per_account.append({
            "account_id": acc.id,
            "account": acc.name,
            "currency": acc.currency,
            "legal_entity": acc.legal_entity,
            "reconciled_as_of": bal.as_of.isoformat(),
            "reconciled_balance_minor": bal.balance_minor,
            "movement_since_minor": movement,
            "transactions_applied": applied,
            "balance_native_minor": native,
            "balance_reporting_minor": converted,
            "status": "ok" if converted is not None else "missing_fx",
        })
    unassigned = [t for t in txns if not t.reversed and t.account_id is None and t.txn_date <= as_of]
    if unassigned:
        issues.append(Issue("warning", "txn_without_account", f"{len(unassigned)} transaction(s) have no account and do not affect the cash balance."))
    if not accounts:
        issues.append(Issue("error", "no_accounts", "No cash accounts are set up. Add accounts and reconciled balances to calculate cash."))
        complete = False
    issues.extend(conv.issues())
    return {
        "as_of": as_of.isoformat(),
        "currency": reporting,
        "available_cash_minor": total if any_balance else None,
        "complete": complete and any_balance,
        "accounts": per_account,
        "issues": [i.as_dict() for i in issues],
        "definition": "Latest reconciled balance per active account, plus inflows minus outflows dated after the reconciliation date up to the as-of date. Transfers move cash between accounts; financing inflows are included in cash.",
    }


# ---------------------------------------------------------------------- burn


def _same_value(o: Txn, i: Txn, fx: FxTable | None, reporting: str | None) -> bool:
    if o.currency == i.currency:
        return o.amount_minor == i.amount_minor
    if fx is None or reporting is None:
        return False
    try:
        a = fx.convert(o.amount_minor, o.currency, reporting, o.txn_date).amount_minor
        b = fx.convert(i.amount_minor, i.currency, reporting, i.txn_date).amount_minor
    except MissingRate:
        return False
    return abs(a - b) <= max(a, b) / 100  # within 1% for cross-currency transfers


def match_intercompany(txns: list[Txn], window_days: int = 5, fx: FxTable | None = None, reporting: str | None = None) -> dict:
    """Pair transfer outflows with transfer inflows of equal value (cross-currency within 1%)."""
    outs = [t for t in txns if t.kind == "transfer" and t.direction == "outflow" and not t.reversed]
    ins = [t for t in txns if t.kind == "transfer" and t.direction == "inflow" and not t.reversed]
    used: set[int] = set()
    pairs = []
    for o in sorted(outs, key=lambda t: t.txn_date):
        for i in sorted(ins, key=lambda t: abs((t.txn_date - o.txn_date).days)):
            if i.id in used or not _same_value(o, i, fx, reporting):
                continue
            if abs((i.txn_date - o.txn_date).days) > window_days:
                continue
            if i.account_id is not None and i.account_id == o.account_id:
                continue
            used.add(i.id)
            pairs.append({
                "out_id": o.id,
                "in_id": i.id,
                "amount_minor": o.amount_minor,
                "currency": o.currency,
                "in_amount_minor": i.amount_minor,
                "in_currency": i.currency,
                "intercompany": bool(o.legal_entity and i.legal_entity and o.legal_entity != i.legal_entity),
                "from_entity": o.legal_entity,
                "to_entity": i.legal_entity,
            })
            break
    matched = {p["out_id"] for p in pairs} | {p["in_id"] for p in pairs}
    unmatched = [t.id for t in outs + ins if t.id not in matched]
    return {"pairs": pairs, "unmatched_ids": unmatched}


def burn(
    txns: list[Txn],
    period_start: date,
    months: int,
    fx: FxTable,
    reporting: str,
    entities: set[str] | None = None,
) -> dict:
    if months <= 0:
        raise ValueError("months must be positive")
    start = date(period_start.year, period_start.month, 1)
    end = add_months(start, months)  # exclusive
    conv = _Converter(fx, reporting)
    outflows = inflows = refunds = 0
    excluded = {"financing_in": 0, "financing_out": 0, "transfers": 0}
    series: dict[str, dict[str, int]] = {m: {"outflows": 0, "inflows": 0} for m in months_between(month_key(start), month_key(add_months(end, -1)))}
    in_scope = []
    for t in txns:
        if t.reversed or not (start <= t.txn_date < end):
            continue
        if entities is not None and t.legal_entity not in entities:
            continue
        in_scope.append(t)
        amt = conv(t.amount_minor, t.currency, t.txn_date, f"txn:{t.id}")
        if amt is None:
            continue
        m = month_key(t.txn_date)
        if t.kind == "transfer":
            excluded["transfers"] += 1
            continue
        if t.kind == "financing":
            excluded["financing_in" if t.direction == "inflow" else "financing_out"] += amt
            continue
        if t.direction == "outflow":
            outflows += amt
            series[m]["outflows"] += amt
        else:
            inflows += amt
            if t.kind == "refund":
                refunds += amt
            series[m]["inflows"] += amt
    ic = match_intercompany(in_scope, fx=fx, reporting=reporting)
    issues = conv.issues()
    active_months = {month_key(t.txn_date) for t in in_scope}
    empty = [m for m in series if m not in active_months]
    if empty:
        issues.append(Issue("warning", "burn_months_without_data", f"No transactions recorded for {', '.join(empty)}; average burn may be understated. Import recent transactions or choose another period."))
    if ic["unmatched_ids"]:
        issues.append(Issue("warning", "unmatched_transfers", f"{len(ic['unmatched_ids'])} transfer(s) have no matching opposite leg; check whether they are external payments."))
    net_total = outflows - inflows
    return {
        "period_start": start.isoformat(),
        "period_end_exclusive": end.isoformat(),
        "months": months,
        "currency": reporting,
        "operating_outflows_minor": outflows,
        "operating_inflows_minor": inflows,
        "refunds_minor": refunds,
        "gross_burn_monthly_minor": _div_round(outflows, months),
        "net_burn_monthly_minor": _div_round(net_total, months),
        "excluded": excluded,
        "intercompany": ic,
        "series": [{"month": k, **v, "net": v["outflows"] - v["inflows"]} for k, v in series.items()],
        "missing_conversions": conv.missing,
        "issues": [i.as_dict() for i in issues],
        "scope": "entities: " + (", ".join(sorted(entities)) if entities else "all legal entities (management view, not statutory consolidation)"),
    }


def simple_runway(available_cash_minor: int | None, net_burn_monthly_minor: int) -> dict:
    if available_cash_minor is None:
        return {"months": None, "status": "incomplete", "note": "Cash balance is incomplete; add reconciled balances."}
    if net_burn_monthly_minor <= 0:
        return {"months": None, "status": "not_depleting", "note": "Average net burn is zero or negative, so the simple ratio does not indicate cash depletion. See the dated forecast."}
    months = (Decimal(available_cash_minor) / Decimal(net_burn_monthly_minor)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return {"months": str(months), "status": "ok", "note": "Available cash / average monthly net operating burn."}


# ------------------------------------------------------------ budget vs actual


def _bucket(program_id, milestone_id, category) -> tuple:
    return (program_id, milestone_id, (category or "uncategorized"))


def actuals(txns: list[Txn], fx: FxTable, reporting: str, rules: list[AllocationRule] | None = None) -> dict:
    """Paid operating spend by (program, milestone, category) in reporting currency.

    Refund inflows reduce the bucket they are allocated to. Shared expenses are
    split only by explicit allocation rules; without a rule they stay unallocated.
    """
    conv = _Converter(fx, reporting)
    by_bucket: dict[tuple, int] = defaultdict(int)
    shared_by_program: dict[int, int] = defaultdict(int)
    shared_unruled = 0
    unallocated = 0
    unallocated_items = []
    for t in txns:
        if t.reversed or t.kind not in ("operating", "refund"):
            continue
        sign = 1 if t.direction == "outflow" else -1
        if t.kind == "operating" and t.direction == "inflow":
            continue  # operating income is not negative spend
        amt = conv(t.amount_minor, t.currency, t.txn_date, f"txn:{t.id}")
        if amt is None:
            continue
        if t.allocation == "direct" and t.program_id is not None:
            by_bucket[_bucket(t.program_id, t.milestone_id, t.category)] += sign * amt
        elif t.allocation == "shared":
            # Shared spend is actual spend of the company-level (shared) budget pool...
            by_bucket[_bucket(None, None, t.category)] += sign * amt
            # ...and is attributed to programs only through an explicit allocation rule.
            rule = _rule_for(rules or [], t.category)
            if rule is None:
                shared_unruled += sign * amt
            else:
                from .money import allocate

                parts = allocate(sign * amt, {str(k): v for k, v in rule.shares_bps.items()}) if sign > 0 else {
                    k: -v for k, v in allocate(amt, {str(k): v for k, v in rule.shares_bps.items()}).items()
                }
                for pid, part in parts.items():
                    shared_by_program[int(pid)] += part
        else:
            unallocated += sign * amt
            unallocated_items.append(t.id)
    return {
        "by_bucket": dict(by_bucket),
        "shared_by_program": dict(shared_by_program),
        "shared_without_rule_minor": shared_unruled,
        "unallocated_minor": unallocated,
        "unallocated_txn_ids": unallocated_items,
        "missing_conversions": conv.missing,
        "issues": [i.as_dict() for i in conv.issues()],
    }


def _rule_for(rules: list[AllocationRule], category: str | None) -> AllocationRule | None:
    for r in rules:
        if r.category and r.category == category:
            return r
    for r in rules:
        if not r.category:
            return r
    return None


def _line_basis(line: BudgetLine) -> int:
    """Approved amount when approved, otherwise the planned estimate."""
    return line.approved_minor if line.approved_minor is not None else line.planned_minor


def _with_contingency(minor: int, bps: int) -> int:
    return minor + int((Decimal(minor) * bps / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def budget_status(
    lines: list[BudgetLine],
    milestones: list[Milestone],
    txns: list[Txn],
    commitments: list[Commitment],
    fx: FxTable,
    reporting: str,
    as_of: date,
    rules: list[AllocationRule] | None = None,
    cost_multipliers_bps: dict[str, int] | None = None,
) -> dict:
    """Budget vs actual vs commitments vs remaining forecast, per bucket.

    remaining = max(0, basis x (1 + contingency) x scenario multiplier - paid actual - open commitments)
    Done or cancelled milestones and closed lines have no remaining cost.
    """
    conv = _Converter(fx, reporting)
    act = actuals(txns, fx, reporting, rules)
    ms = {m.id: m for m in milestones}
    mult = cost_multipliers_bps or {}
    buckets: dict[tuple, dict] = {}

    def b(key):
        if key not in buckets:
            buckets[key] = {
                "program_id": key[0], "milestone_id": key[1], "category": key[2],
                "planned_minor": 0, "approved_minor": 0, "unapproved_lines": 0,
                "contingency_minor": 0, "basis_with_contingency_minor": 0,
                "actual_minor": 0, "open_commitments_minor": 0, "line_ids": [],
                "closed": False,
            }
        return buckets[key]

    for line in lines:
        bk = b(_bucket(line.program_id, line.milestone_id, line.category))
        planned = conv(line.planned_minor, line.currency, as_of, f"line:{line.id}")
        basis = conv(_line_basis(line), line.currency, as_of, f"line:{line.id}")
        if planned is None or basis is None:
            continue
        bk["planned_minor"] += planned
        if line.approved_minor is not None:
            bk["approved_minor"] += conv(line.approved_minor, line.currency, as_of, f"line:{line.id}") or 0
        else:
            bk["unapproved_lines"] += 1
        with_c = _with_contingency(basis, line.contingency_bps)
        factor = mult.get(line.category, 10000)
        with_c = int((Decimal(with_c) * factor / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        bk["contingency_minor"] += _with_contingency(basis, line.contingency_bps) - basis
        bk["basis_with_contingency_minor"] += with_c
        bk["line_ids"].append(line.id)
        if line.status == "closed":
            bk["closed"] = True
    for key, amount in act["by_bucket"].items():
        b(key)["actual_minor"] += amount
    for c in commitments:
        if c.status != "open":
            continue
        amt = conv(c.amount_minor, c.currency, as_of, f"commitment:{c.id}")
        if amt is None:
            continue
        b(_bucket(c.program_id, c.milestone_id, c.category))["open_commitments_minor"] += amt

    out = []
    for key, bk in buckets.items():
        m = ms.get(bk["milestone_id"])
        finished = bool(m and m.status in ("done", "cancelled")) or bk["closed"]
        committed_total = bk["actual_minor"] + bk["open_commitments_minor"]
        remaining = 0 if finished else max(0, bk["basis_with_contingency_minor"] - committed_total)
        overrun = max(0, committed_total - bk["basis_with_contingency_minor"])
        approved = bk["approved_minor"]
        out.append({
            **bk,
            "remaining_forecast_minor": remaining,
            "forecast_at_completion_minor": committed_total + remaining,
            "variance_vs_approved_minor": (committed_total + remaining - approved) if approved else None,
            "overrun_minor": overrun,
            "finished": finished,
        })
    out.sort(key=lambda r: (r["program_id"] or 0, r["milestone_id"] or 0, r["category"]))
    issues = conv.issues() + [Issue(**i) for i in act["issues"]]
    return {
        "currency": reporting,
        "as_of": as_of.isoformat(),
        "buckets": out,
        "shared_by_program": act["shared_by_program"],
        "shared_without_rule_minor": act["shared_without_rule_minor"],
        "unallocated_minor": act["unallocated_minor"],
        "unallocated_txn_ids": act["unallocated_txn_ids"],
        "issues": [i.as_dict() if isinstance(i, Issue) else i for i in issues],
        "definition": "Remaining forecast = max(0, (approved, or planned if not yet approved) + contingency - paid actual - open commitments). Commitments are kept separate from paid actuals; when a commitment is paid and linked, it leaves 'open commitments' and enters 'actual', so it is counted once.",
    }


def rollup(buckets: list[dict], key: str) -> list[dict]:
    """Sum buckets by a key. Variance vs approved only covers buckets that have
    an approved budget; unapproved estimates are reported separately."""
    fields = ["planned_minor", "approved_minor", "contingency_minor", "actual_minor", "open_commitments_minor", "remaining_forecast_minor", "forecast_at_completion_minor", "overrun_minor"]
    agg: dict = {}
    for r in buckets:
        k = r[key]
        if k not in agg:
            agg[k] = {key: k, **{f: 0 for f in fields}, "forecast_on_approved_minor": 0, "unapproved_forecast_minor": 0}
        for f in fields:
            agg[k][f] += r[f] or 0
        if r["approved_minor"]:
            agg[k]["forecast_on_approved_minor"] += r["forecast_at_completion_minor"]
        else:
            agg[k]["unapproved_forecast_minor"] += r["forecast_at_completion_minor"]
    for a in agg.values():
        a["variance_vs_approved_minor"] = a["forecast_on_approved_minor"] - a["approved_minor"] if a["approved_minor"] else None
    return list(agg.values())


# ------------------------------------------------------------------ forecast


@dataclass
class ForecastInputs:
    as_of: date
    reporting: str
    fx: FxTable
    start_cash_minor: int | None
    reserve_minor: int
    horizon_months: int
    lines: list[BudgetLine]
    milestones: list[Milestone]
    txns: list[Txn]
    commitments: list[Commitment]
    planned_flows: list[PlannedFlow]
    rules: list[AllocationRule] = field(default_factory=list)
    include_hypothetical: bool = False
    cost_multipliers_bps: dict[str, int] = field(default_factory=dict)
    extra_flows: list[PlannedFlow] = field(default_factory=list)  # scenario-only flows


def split_proportional(minor: int, weights: dict[str, int]) -> dict[str, int]:
    """Largest-remainder split; parts always sum to `minor`."""
    total = sum(w for w in weights.values() if w > 0)
    keys = [k for k, w in weights.items() if w > 0]
    if not keys:
        return {}
    raw = {k: Decimal(minor) * weights[k] / total for k in keys}
    parts = {k: int(v.to_integral_value(rounding="ROUND_FLOOR")) for k, v in raw.items()}
    rem = minor - sum(parts.values())
    for k in sorted(keys, key=lambda k: (-(raw[k] - parts[k]), k))[:rem]:
        parts[k] += 1
    return parts


def _ms_name(ms: dict, mid) -> str:
    m = ms.get(mid)
    return f"milestone '{m.name}'" if m else "company-level"


def forecast(inp: ForecastInputs) -> dict:
    fx_note = "Future amounts are converted at the latest recorded rate on the as-of date; FX movements are not modeled."
    status = budget_status(inp.lines, inp.milestones, inp.txns, inp.commitments, inp.fx, inp.reporting, inp.as_of, inp.rules, inp.cost_multipliers_bps)
    conv = _Converter(inp.fx, inp.reporting)
    start_m = month_key(inp.as_of)
    months = [month_key(add_months(parse_month(start_m), i)) for i in range(inp.horizon_months)]
    flows = {m: {"budget_outflows": 0, "commitment_outflows": 0, "other_outflows": 0, "inflows": 0} for m in months}
    beyond = 0
    notes: list[Issue] = []
    ms = {m.id: m for m in inp.milestones}
    lines_by_bucket: dict[tuple, list[BudgetLine]] = defaultdict(list)
    for line in inp.lines:
        lines_by_bucket[_bucket(line.program_id, line.milestone_id, line.category)].append(line)
    per_milestone_month: dict[int | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def put(month: str, kind: str, amount: int, milestone_id=None):
        nonlocal beyond
        if month < start_m:
            month = start_m
        if month not in flows:
            beyond += amount if kind != "inflows" else 0
            return
        flows[month][kind] += amount
        if kind in ("budget_outflows", "commitment_outflows"):
            per_milestone_month[milestone_id][month] += amount

    for bk in status["buckets"]:
        remaining = bk["remaining_forecast_minor"]
        if remaining <= 0:
            continue
        key = (bk["program_id"], bk["milestone_id"], bk["category"])
        shape: dict[str, int] = defaultdict(int)
        for line in lines_by_bucket.get(key, []):
            for mk, amt in line.schedule.items():
                if mk >= start_m:
                    c = conv(amt, line.currency, inp.as_of, f"schedule:{line.id}")
                    shape[mk] += c or 0
        if not shape:
            m = ms.get(bk["milestone_id"])
            if m and m.planned_end and month_key(m.planned_end) >= start_m:
                first = max(start_m, month_key(m.planned_start) if m.planned_start else start_m)
                for mk in months_between(first, month_key(m.planned_end)):
                    shape[mk] = 1
                notes.append(Issue("info", "even_spread", f"No future monthly schedule for {bk['category']} ({_ms_name(ms, bk['milestone_id'])}); remaining cost spread evenly to the planned end date."))
            else:
                shape[start_m] = 1
                notes.append(Issue("warning", "schedule_elapsed", f"Remaining cost for {bk['category']} ({_ms_name(ms, bk['milestone_id'])}) has no future schedule or date; assumed due this month."))
        for mk, part in split_proportional(remaining, dict(shape)).items():
            put(mk, "budget_outflows", part, bk["milestone_id"])

    for c in inp.commitments:
        if c.status != "open":
            continue
        amt = conv(c.amount_minor, c.currency, inp.as_of, f"commitment:{c.id}")
        if amt is None:
            continue
        if c.expected_date is None or month_key(c.expected_date) < start_m:
            notes.append(Issue("warning", "commitment_overdue_or_undated", f"Open commitment to {c.counterparty or c.id} is undated or past due; assumed payable this month."))
        put(month_key(c.expected_date) if c.expected_date else start_m, "commitment_outflows", amt, c.milestone_id)

    for f in list(inp.planned_flows) + list(inp.extra_flows):
        if f.certainty == "hypothetical" and not inp.include_hypothetical:
            continue
        if f.flow_date < inp.as_of:
            continue
        amt = conv(f.amount_minor, f.currency, inp.as_of, f"flow:{f.label}")
        if amt is None:
            continue
        put(month_key(f.flow_date), "inflows" if f.direction == "inflow" else "other_outflows", amt)

    table = []
    cash = inp.start_cash_minor
    below_reserve = cash_out = None
    min_cash = None
    for m in months:
        f = flows[m]
        out = f["budget_outflows"] + f["commitment_outflows"] + f["other_outflows"]
        opening = cash
        if cash is not None:
            cash = cash - out + f["inflows"]
            if min_cash is None or cash < min_cash:
                min_cash = cash
            if below_reserve is None and cash < inp.reserve_minor:
                below_reserve = m
            if cash_out is None and cash < 0:
                cash_out = m
        table.append({"month": m, "opening_minor": opening, **f, "total_outflows_minor": out, "closing_minor": cash})

    shared_months = [m for m in months if any(
        mk == m for line in inp.lines if line.program_id is None and line.status != "closed" for mk in line.schedule)]
    if shared_months and shared_months[-1] < months[-1]:
        notes.append(Issue("warning", "shared_costs_end", f"Company running costs (shared budget lines) are budgeted only through {shared_months[-1]}; later months of the forecast exclude them."))
    if inp.start_cash_minor is None:
        notes.append(Issue("error", "incomplete_cash", "No complete reconciled cash balance, so projected cash and forecast runway cannot be calculated. Flows are still shown."))
    if beyond:
        notes.append(Issue("info", "beyond_horizon", f"{beyond} (minor units, {inp.reporting}) of planned outflows fall after the {inp.horizon_months}-month horizon."))
    issues = [Issue(**i) for i in status["issues"]] + conv.issues() + notes
    runway_months = None
    if below_reserve:
        runway_months = months.index(below_reserve)
    return {
        "as_of": inp.as_of.isoformat(),
        "currency": inp.reporting,
        "start_cash_minor": inp.start_cash_minor,
        "reserve_minor": inp.reserve_minor,
        "horizon_months": inp.horizon_months,
        "months": table,
        "below_reserve_month": below_reserve,
        "cash_out_month": cash_out,
        "full_months_above_reserve": runway_months,
        "min_cash_minor": min_cash,
        "outflows_after_horizon_minor": beyond,
        "per_milestone_month": {str(k): dict(v) for k, v in per_milestone_month.items()},
        "budget_status": status,
        "issues": _dedupe_issues(issues),
        "includes_hypothetical": inp.include_hypothetical,
        "method": (
            "Starting from reconciled available cash, each month subtracts the remaining forecast cost of budget lines "
            "(distributed over each line's future monthly schedule, or evenly to the milestone end date), open commitments "
            "at their expected payment month, and confirmed planned flows. Hypothetical inflows are included only in scenarios. "
            + fx_note
        ),
    }


def _dedupe_issues(issues: list[Issue]) -> list[dict]:
    seen, out = set(), []
    for i in issues:
        d = i.as_dict() if isinstance(i, Issue) else i
        k = (d["code"], d["message"])
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


# --------------------------------------------------------- milestone funding


def dependency_closure(milestone_id: int, milestones: list[Milestone]) -> list[int]:
    ms = {m.id: m for m in milestones}
    seen: list[int] = []
    stack = [milestone_id]
    while stack:
        mid = stack.pop()
        if mid in seen or mid not in ms:
            continue
        seen.append(mid)
        stack.extend(ms[mid].depends_on)
    return seen


def milestone_funding(milestone_id: int, inp: ForecastInputs, fc: dict | None = None) -> dict:
    """Is the selected milestone funded under the forecast?

    Direct cost to reach = remaining forecast cost + open commitments for the
    milestone and its unfinished prerequisites. Funding test = projected
    month-end cash stays at or above the minimum reserve through the
    milestone's planned end month, counting every other planned flow too.
    """
    fc = fc or forecast(inp)
    ms = {m.id: m for m in inp.milestones}
    if milestone_id not in ms:
        raise KeyError(f"milestone {milestone_id} not found")
    target = ms[milestone_id]
    chain = [mid for mid in dependency_closure(milestone_id, inp.milestones) if ms[mid].status not in ("done", "cancelled")]
    comps = []
    total = 0
    for bk in fc["budget_status"]["buckets"]:
        if bk["milestone_id"] in chain:
            amount = bk["remaining_forecast_minor"] + bk["open_commitments_minor"]
            if amount:
                comps.append({"milestone_id": bk["milestone_id"], "category": bk["category"], "remaining_minor": bk["remaining_forecast_minor"], "open_commitments_minor": bk["open_commitments_minor"]})
                total += amount
    gaps: list[str] = []
    if target.planned_end is None:
        gaps.append("The milestone has no planned end date, so the funding test cannot be dated.")
        end_month = None
    else:
        end_month = month_key(target.planned_end)
        first = fc["months"][0]["month"] if fc["months"] else end_month
        if end_month < first:
            gaps.append(f"The milestone is overdue (planned end {target.planned_end.isoformat()}); funding is tested through the current month only.")
            end_month = first
    unbudgeted = [mid for mid in chain if not any(bk["milestone_id"] == mid for bk in fc["budget_status"]["buckets"])]
    if unbudgeted:
        gaps.append(f"{len(unbudgeted)} milestone(s) in the dependency chain have no budget lines: {', '.join(ms[m].name for m in unbudgeted)}.")
    unapproved = sum(bk["unapproved_lines"] for bk in fc["budget_status"]["buckets"] if bk["milestone_id"] in chain)
    if unapproved:
        gaps.append(f"{unapproved} budget line(s) in the chain are unapproved estimates.")
    funded = None
    gap = None
    min_cash = None
    chain_budgeted = any(bk["milestone_id"] in chain for bk in fc["budget_status"]["buckets"])
    if not chain_budgeted and chain:
        gaps.append("No budget exists for this milestone or its prerequisites, so funding cannot be assessed.")
    if end_month and fc["start_cash_minor"] is not None and (chain_budgeted or not chain):
        window = [r for r in fc["months"] if r["month"] <= end_month]
        if window:
            min_cash = min(r["closing_minor"] for r in window)
            funded = min_cash >= inp.reserve_minor
            gap = max(0, inp.reserve_minor - min_cash)
        if end_month > fc["months"][-1]["month"]:
            gaps.append("The milestone ends after the forecast horizon.")
    elif fc["start_cash_minor"] is None:
        gaps.append("Cash balance is incomplete, so funding cannot be confirmed.")
    return {
        "milestone_id": milestone_id,
        "milestone": target.name,
        "planned_end": target.planned_end.isoformat() if target.planned_end else None,
        "dependency_chain": [{"id": m, "name": ms[m].name, "status": ms[m].status} for m in chain],
        "direct_cost_to_reach_minor": total,
        "components": comps,
        "min_projected_cash_through_milestone_minor": min_cash,
        "reserve_minor": inp.reserve_minor,
        "funded": funded,
        "funding_gap_minor": gap,
        "below_reserve_month": fc["below_reserve_month"],
        "currency": inp.reporting,
        "gaps": gaps,
        "definition": "Funded = projected month-end cash (all programs, commitments, confirmed flows) stays at or above the minimum reserve through the milestone's planned end month.",
    }


# ----------------------------------------------------------------- scenarios


SCENARIO_TEMPLATES = {
    "base": {
        "description": "Approved baseline: no changes.",
        "assumptions": {},
    },
    "accelerated": {
        "description": "Illustrative assumption: not-yet-started milestones start 2 months earlier and CRO/clinical costs rise 10% for expedited work. Edit to fit.",
        "assumptions": {"shift_unstarted_months": -2, "category_cost_change_pct": {"CRO services": 10, "Clinical / field studies": 10}},
    },
    "conservative": {
        "description": "Illustrative assumption: not-yet-started milestones slip 3 months and CRO, CMC, and clinical costs rise 20%. Edit to fit.",
        "assumptions": {"shift_unstarted_months": 3, "category_cost_change_pct": {"CRO services": 20, "Manufacturing / CMC": 20, "Clinical / field studies": 20}},
    },
}


def _shift_date(d: date | None, n: int) -> date | None:
    return add_months(d, n) if d else None


def apply_scenario(base: ForecastInputs, assumptions: dict) -> ForecastInputs:
    """Return a modified deep copy; the approved baseline is never mutated.

    Supported assumptions:
    - milestone_shifts: {milestone_id: months}  (+ delays, - accelerates)
    - shift_unstarted_months: int  (applies to milestones with status 'planned')
    - propagate_to_dependents: bool (default True)
    - category_cost_change_pct: {category: pct}  (applied to remaining cost)
    - financing: [{label, date, amount_minor, currency}]  (hypothetical inflows)
    - extra_monthly_cost: {amount_minor, currency, start_month, months, label}
    - include_hypothetical_planned_flows: bool
    """
    inp = copy.deepcopy(base)
    shifts: dict[int, int] = {int(k): int(v) for k, v in (assumptions.get("milestone_shifts") or {}).items()}
    if assumptions.get("shift_unstarted_months"):
        for m in inp.milestones:
            if m.status == "planned":
                shifts.setdefault(m.id, int(assumptions["shift_unstarted_months"]))
    if assumptions.get("propagate_to_dependents", True) and shifts:
        changed = True
        while changed:
            changed = False
            for m in inp.milestones:
                if m.status in ("done", "cancelled"):
                    continue
                for dep in m.depends_on:
                    if dep in shifts and shifts[dep] > 0 and shifts.get(m.id, 0) < shifts[dep]:
                        shifts[m.id] = shifts[dep]
                        changed = True
    for m in inp.milestones:
        n = shifts.get(m.id)
        if n and m.status not in ("done", "cancelled"):
            m.planned_start = _shift_date(m.planned_start, n)
            m.planned_end = _shift_date(m.planned_end, n)
    for line in inp.lines:
        n = shifts.get(line.milestone_id or -1)
        if n:
            line.schedule = {month_key(add_months(parse_month(k), n)): v for k, v in line.schedule.items()}
    for c in inp.commitments:
        n = shifts.get(c.milestone_id or -1)
        if n and c.expected_date and assumptions.get("shift_commitments", True):
            c.expected_date = _shift_date(c.expected_date, n)
    mult = {}
    for cat, pct in (assumptions.get("category_cost_change_pct") or {}).items():
        mult[cat] = 10000 + int(Decimal(str(pct)) * 100)
    inp.cost_multipliers_bps = mult
    extra: list[PlannedFlow] = []
    for f in assumptions.get("financing") or []:
        extra.append(PlannedFlow(label=f.get("label") or "Hypothetical financing", flow_date=date.fromisoformat(f["date"]), amount_minor=int(f["amount_minor"]), currency=f["currency"], direction="inflow", kind="financing", certainty="confirmed"))
    emc = assumptions.get("extra_monthly_cost")
    if emc and int(emc.get("amount_minor") or 0) > 0:
        start = parse_month(emc.get("start_month") or month_key(inp.as_of))
        for i in range(int(emc.get("months") or inp.horizon_months)):
            extra.append(PlannedFlow(label=emc.get("label") or "Extra monthly cost", flow_date=max(add_months(start, i), inp.as_of), amount_minor=int(emc["amount_minor"]), currency=emc["currency"], direction="outflow"))
    inp.extra_flows = extra
    inp.include_hypothetical = bool(assumptions.get("include_hypothetical_planned_flows"))
    return inp


def compare(base_fc: dict, scen_fc: dict) -> dict:
    def last_cash(fc):
        return fc["months"][-1]["closing_minor"] if fc["months"] else None

    def delta(a, b):
        return None if a is None or b is None else b - a

    return {
        "below_reserve_month": {"base": base_fc["below_reserve_month"], "scenario": scen_fc["below_reserve_month"]},
        "cash_out_month": {"base": base_fc["cash_out_month"], "scenario": scen_fc["cash_out_month"]},
        "min_cash_minor": {"base": base_fc["min_cash_minor"], "scenario": scen_fc["min_cash_minor"], "delta": delta(base_fc["min_cash_minor"], scen_fc["min_cash_minor"])},
        "cash_at_horizon_minor": {"base": last_cash(base_fc), "scenario": last_cash(scen_fc), "delta": delta(last_cash(base_fc), last_cash(scen_fc))},
        "months": [
            {"month": a["month"], "base_closing_minor": a["closing_minor"], "scenario_closing_minor": b["closing_minor"], "base_outflows_minor": a["total_outflows_minor"], "scenario_outflows_minor": b["total_outflows_minor"]}
            for a, b in zip(base_fc["months"], scen_fc["months"])
        ],
    }
