from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest

from app.finance import calc
from app.finance.calc import Account, Balance, BudgetLine, Commitment, ForecastInputs, Milestone, PlannedFlow, Txn
from app.finance.fx import FxTable, MissingRate, Rate
from app.finance.money import allocate, parse_amount, to_minor

FX = FxTable([
    Rate("USD", "HKD", Decimal("7.80"), date(2026, 1, 1), "manual"),
    Rate("USD", "CNY", Decimal("7.10"), date(2026, 1, 1), "manual"),
])


# ------------------------------------------------------------------- money


def test_parse_amount_formats():
    assert parse_amount("1,234.50").value == Decimal("1234.50")
    assert parse_amount("(200.00)").value == Decimal("-200.00")
    assert parse_amount("200.00-").value == Decimal("-200.00")
    p = parse_amount("HK$1,000")
    assert p.value == Decimal("1000") and p.currency_hint == "HKD"
    assert parse_amount("RMB 88.8").currency_hint == "CNY"
    amb = parse_amount("$50")
    assert amb.value == Decimal("50") and any("ambiguous" in i for i in amb.issues)
    assert parse_amount("12,5").value is None  # decimal comma is not guessed
    assert parse_amount("abc").value is None
    assert parse_amount(0.1).value == Decimal("0.1")


def test_rounding_half_up_and_allocation_sums_exactly():
    assert to_minor(Decimal("0.005"), "USD") == 1
    assert to_minor(Decimal("-0.005"), "USD") == -1
    parts = allocate(100, {"a": 3333, "b": 3333, "c": 3334})
    assert sum(parts.values()) == 100
    with pytest.raises(ValueError):
        allocate(100, {"a": 5000})


# ---------------------------------------------------------------------- fx


def test_fx_direct_inverse_cross_and_missing():
    assert FX.convert(10000, "USD", "HKD", date(2026, 3, 1)).amount_minor == 78000
    inv = FX.convert(78000, "HKD", "USD", date(2026, 3, 1))
    assert inv.amount_minor == 10000 and inv.method == "inverse"
    ecb = FxTable([Rate("EUR", "USD", Decimal("1.10"), date(2026, 3, 2), "ECB", "ecb_reference"), Rate("EUR", "HKD", Decimal("8.58"), date(2026, 3, 2), "ECB", "ecb_reference")])
    c = ecb.convert(10000, "USD", "HKD", date(2026, 3, 3))
    assert c.method == "cross_eur" and c.amount_minor == 78000
    with pytest.raises(MissingRate):
        FX.convert(100, "USD", "HKD", date(2025, 12, 1))  # before any rate
    assert FX.convert(100, "USD", "HKD", date(2026, 3, 1)).stale is True


# -------------------------------------------------------------------- cash


def _accounts():
    return [Account(1, "HSBC HKD", "HKD", "Ocra HK"), Account(2, "Chase USD", "USD", "Ocra US")]


def test_cash_incomplete_without_reconciled_balance():
    res = calc.cash_position(_accounts(), [Balance(1, date(2026, 6, 30), 780000_00, "HKD")], [], date(2026, 7, 15), FX, "USD")
    assert res["complete"] is False
    assert any(i["code"] == "missing_balance" for i in res["issues"])


def test_partial_import_does_not_become_cash_balance():
    txns = [Txn(1, date(2026, 7, 2), 5000_00, "USD", "inflow", account_id=2)]
    res = calc.cash_position(_accounts()[1:], [], txns, date(2026, 7, 15), FX, "USD")
    assert res["available_cash_minor"] is None and res["complete"] is False


def test_cash_rolls_forward_from_reconciliation_date():
    bals = [Balance(1, date(2026, 6, 30), 780000_00, "HKD"), Balance(2, date(2026, 6, 30), 50000_00, "USD")]
    txns = [
        Txn(1, date(2026, 6, 30), 999_00, "USD", "outflow", account_id=2),  # on the reconciliation date: already in balance
        Txn(2, date(2026, 7, 5), 1000_00, "USD", "outflow", account_id=2),
        Txn(3, date(2026, 7, 6), 7800_00, "HKD", "inflow", account_id=1, kind="refund"),
        Txn(4, date(2026, 7, 7), 100_00, "USD", "outflow", account_id=2, reversed=True),
    ]
    res = calc.cash_position(_accounts(), bals, txns, date(2026, 7, 15), FX, "USD")
    assert res["complete"] is True
    # HKD 787,800 -> USD 101,000 ; USD 49,000
    assert res["available_cash_minor"] == 101000_00 + 49000_00


# -------------------------------------------------------------------- burn


def test_burn_excludes_transfers_and_financing_and_handles_refunds():
    txns = [
        Txn(1, date(2026, 4, 3), 30000_00, "USD", "outflow", category="CRO services"),
        Txn(2, date(2026, 5, 3), 7800_00 * 10, "HKD", "outflow"),  # = USD 10,000
        Txn(3, date(2026, 5, 9), 1000_00, "USD", "inflow", kind="refund"),
        Txn(4, date(2026, 6, 1), 2_000_000_00, "USD", "inflow", kind="financing"),
        Txn(5, date(2026, 6, 2), 5000_00, "USD", "outflow", kind="transfer", legal_entity="Ocra US", account_id=2),
        Txn(6, date(2026, 6, 3), 5000_00, "USD", "inflow", kind="transfer", legal_entity="Ocra HK", account_id=1),
        Txn(7, date(2026, 7, 1), 99999_00, "USD", "outflow"),  # outside period
    ]
    b = calc.burn(txns, date(2026, 4, 1), 3, FX, "USD")
    assert b["operating_outflows_minor"] == 40000_00
    assert b["operating_inflows_minor"] == 1000_00
    assert b["gross_burn_monthly_minor"] == 13333_33
    assert b["net_burn_monthly_minor"] == 13000_00
    assert b["excluded"]["financing_in"] == 2_000_000_00
    assert b["intercompany"]["pairs"][0]["intercompany"] is True
    assert not b["intercompany"]["unmatched_ids"]


def test_simple_runway_non_positive_burn():
    assert calc.simple_runway(100, 0)["status"] == "not_depleting"
    assert calc.simple_runway(100, -5)["months"] is None
    assert calc.simple_runway(None, 10)["status"] == "incomplete"
    assert calc.simple_runway(1000, 300)["months"] == "3.3"


def test_missing_fx_is_reported_not_combined():
    txns = [Txn(1, date(2026, 4, 3), 100_00, "CNY", "outflow"), Txn(2, date(2026, 4, 3), 100_00, "USD", "outflow")]
    fx = FxTable([])
    b = calc.burn(txns, date(2026, 4, 1), 1, fx, "USD")
    assert b["operating_outflows_minor"] == 100_00
    assert len(b["missing_conversions"]) == 1


# ---------------------------------------------------------------- forecast


def _inputs(cash=300000_00, reserve=50000_00):
    ms = [
        Milestone(10, 1, "GLP tox study", date(2026, 8, 1), date(2026, 12, 31), "in_progress"),
        Milestone(11, 1, "Pilot field study", date(2027, 1, 1), date(2027, 6, 30), "planned", depends_on=[10]),
    ]
    lines = [
        BudgetLine(100, 1, 10, "CRO services", "USD", 120000_00, 120000_00, 1000, "approved", {"2026-08": 40000_00, "2026-09": 40000_00, "2026-10": 40000_00}),
        BudgetLine(101, 1, 11, "Clinical / field studies", "USD", 180000_00, None, 0, "draft", {f"2027-0{i}": 30000_00 for i in range(1, 7)}),
        BudgetLine(102, None, None, "Personnel", "HKD", 7800_00 * 10 * 12, 7800_00 * 10 * 12, 0, "approved", {f"2026-{m:02d}": 7800_00 * 10 for m in range(8, 13)} | {f"2027-{m:02d}": 7800_00 * 10 for m in range(1, 8)}),
    ]
    txns = [Txn(1, date(2026, 8, 10), 30000_00, "USD", "outflow", category="CRO services", program_id=1, milestone_id=10, allocation="direct")]
    commitments = [Commitment(1, 1, 10, "CRO services", "USD", 20000_00, date(2026, 9, 15), counterparty="CRO A")]
    return ForecastInputs(as_of=date(2026, 8, 20), reporting="USD", fx=FX, start_cash_minor=cash, reserve_minor=reserve, horizon_months=12,
                          lines=lines, milestones=ms, txns=txns, commitments=commitments, planned_flows=[])


def test_budget_status_keeps_commitments_separate_and_no_double_count():
    inp = _inputs()
    st = calc.budget_status(inp.lines, inp.milestones, inp.txns, inp.commitments, FX, "USD", inp.as_of)
    b = next(x for x in st["buckets"] if x["milestone_id"] == 10)
    assert b["basis_with_contingency_minor"] == 132000_00
    assert b["actual_minor"] == 30000_00
    assert b["open_commitments_minor"] == 20000_00
    assert b["remaining_forecast_minor"] == 82000_00
    # paying the commitment: commitment closes, actual rises -> remaining unchanged
    inp.commitments[0].status = "paid"
    inp.txns.append(Txn(2, date(2026, 9, 15), 20000_00, "USD", "outflow", category="CRO services", program_id=1, milestone_id=10, allocation="direct", commitment_id=1))
    st2 = calc.budget_status(inp.lines, inp.milestones, inp.txns, inp.commitments, FX, "USD", inp.as_of)
    b2 = next(x for x in st2["buckets"] if x["milestone_id"] == 10)
    assert b2["remaining_forecast_minor"] == 82000_00
    assert b2["forecast_at_completion_minor"] == b["forecast_at_completion_minor"]


def test_forecast_sums_and_runway():
    fc = calc.forecast(_inputs())
    total_out = sum(m["total_outflows_minor"] for m in fc["months"])
    # 82,000 CRO remaining + 20,000 commitment + 180,000 field study + personnel 12 x 10,000 (Aug..Jul)
    assert total_out == 82000_00 + 20000_00 + 180000_00 + 120000_00
    assert fc["months"][-1]["closing_minor"] == 300000_00 - total_out
    assert fc["below_reserve_month"] is not None
    assert fc["cash_out_month"] is not None


def test_forecast_incomplete_cash_still_shows_flows():
    fc = calc.forecast(_inputs(cash=None))
    assert fc["months"][0]["closing_minor"] is None
    assert any(i["code"] == "incomplete_cash" for i in fc["issues"])
    assert sum(m["total_outflows_minor"] for m in fc["months"]) > 0


def test_milestone_funding_and_gap():
    inp = _inputs(cash=1_000_000_00)
    f = calc.milestone_funding(11, inp)
    assert f["funded"] is True
    assert f["direct_cost_to_reach_minor"] == 82000_00 + 20000_00 + 180000_00
    assert any("unapproved" in g for g in f["gaps"])
    poor = calc.milestone_funding(11, _inputs(cash=200000_00))
    assert poor["funded"] is False and poor["funding_gap_minor"] > 0


def test_scenario_delay_does_not_mutate_baseline():
    base = _inputs()
    snapshot = copy.deepcopy((base.lines, base.milestones, base.commitments))
    scen = calc.apply_scenario(base, {"milestone_shifts": {"10": 3}})
    assert (base.lines, base.milestones, base.commitments) == snapshot
    m11 = next(m for m in scen.milestones if m.id == 11)
    assert m11.planned_start == date(2027, 4, 1)  # dependent shifted too
    b, s = calc.forecast(base), calc.forecast(scen)
    cmp = calc.compare(b, s)
    assert cmp["months"][1]["scenario_outflows_minor"] < cmp["months"][1]["base_outflows_minor"]


def test_hypothetical_financing_only_in_scenario():
    base = _inputs()
    base.planned_flows.append(PlannedFlow("Possible seed extension", date(2026, 12, 1), 500000_00, "USD", "inflow", "financing", "hypothetical"))
    b = calc.forecast(base)
    assert all(m["inflows"] == 0 for m in b["months"])
    s = calc.forecast(calc.apply_scenario(base, {"include_hypothetical_planned_flows": True}))
    assert sum(m["inflows"] for m in s["months"]) == 500000_00


def test_category_cost_change_scenario():
    base = _inputs()
    s = calc.forecast(calc.apply_scenario(base, {"category_cost_change_pct": {"Clinical / field studies": 20}}))
    b = calc.forecast(base)
    diff = sum(m["total_outflows_minor"] for m in s["months"]) - sum(m["total_outflows_minor"] for m in b["months"])
    assert diff == 36000_00


def test_shared_cost_needs_explicit_rule():
    txns = [Txn(1, date(2026, 5, 1), 10000_00, "USD", "outflow", category="Facilities", allocation="shared")]
    a = calc.actuals(txns, FX, "USD", [])
    assert a["shared_without_rule_minor"] == 10000_00 and not a["shared_by_program"]
    assert a["by_bucket"][(None, None, "Facilities")] == 10000_00  # counts against the shared pool
    rule = calc.AllocationRule(1, "Lab share", None, {1: 6000, 2: 4000})
    a2 = calc.actuals(txns, FX, "USD", [rule])
    assert a2["shared_by_program"] == {1: 6000_00, 2: 4000_00}


def test_shared_payments_reduce_company_budget_remaining():
    lines = [BudgetLine(1, None, None, "Personnel", "USD", 120000_00, 120000_00, 0, "approved", {f"2026-{m:02d}": 10000_00 for m in range(1, 13)})]
    txns = [Txn(i, date(2026, i, 5), 10000_00, "USD", "outflow", category="Personnel", allocation="shared") for i in range(1, 7)]
    st = calc.budget_status(lines, [], txns, [], FX, "USD", date(2026, 7, 10))
    assert st["buckets"][0]["remaining_forecast_minor"] == 60000_00


def test_overdue_milestone_funding_is_tested_through_current_month():
    inp = _inputs(cash=1_000_000_00)
    inp.milestones[0].planned_end = date(2026, 7, 31)
    f = calc.milestone_funding(10, inp)
    assert f["funded"] is True and any("overdue" in g for g in f["gaps"])


def test_rollup_variance_excludes_unapproved_estimates():
    inp = _inputs()
    st = calc.budget_status(inp.lines, inp.milestones, inp.txns, inp.commitments, FX, "USD", inp.as_of)
    prog = next(r for r in calc.rollup(st["buckets"], "program_id") if r["program_id"] == 1)
    assert prog["unapproved_forecast_minor"] == 180000_00  # unapproved field study, not an overrun
    assert prog["variance_vs_approved_minor"] == prog["forecast_on_approved_minor"] - 120000_00


def test_unbudgeted_milestone_funding_is_unknown():
    inp = _inputs(cash=1_000_000_00)
    inp.milestones.append(Milestone(12, 1, "Unbudgeted review", date(2026, 9, 1), date(2026, 11, 30), "planned"))
    f = calc.milestone_funding(12, inp)
    assert f["funded"] is None and any("No budget" in g for g in f["gaps"])


def test_burn_warns_on_months_without_data():
    txns = [Txn(1, date(2026, 4, 3), 100_00, "USD", "outflow")]
    b = calc.burn(txns, date(2026, 4, 1), 3, FX, "USD")
    assert any(i["code"] == "burn_months_without_data" for i in b["issues"])
