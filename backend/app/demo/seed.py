"""Synthetic demonstration workspace.

Everything created here is fictional, tagged origin='synthetic', and uses a
fixed as-of date so screenshots and evaluations are reproducible. None of it
describes a real company, product, budget, or bank account.

Usage:  python -m app.demo.seed            (demo database, resets it)
        python -m app.demo.seed --into-current   (adds synthetic records to the
            currently configured database, e.g. a live-mode class demo DB)
"""

from __future__ import annotations

import argparse
import sys

from ..config import get_settings
from ..db import connect, init_db, jdump, log_activity, migrate, set_setting, utc_now
from ..research.registry import seed as seed_registry

AS_OF = "2026-10-24"
SYN = "synthetic"


def _m(amount: float | int) -> int:
    return int(round(amount * 100))


def seed_programs(conn) -> dict:
    now = utc_now()
    progs = [
        dict(code="HX-101", name="Hypothetical Program Alpha", description="HYPOTHETICAL DEMO. Oral small-molecule kinase inhibitor for canine mast cell tumors; initially considering the US and EU.",
             therapeutic_area="oncology", indication="mast cell tumor", use_type="veterinary", species=["dog"], target="receptor tyrosine kinase (illustrative)", mechanism="kinase inhibition",
             modality="small molecule", molecule_category="small_molecule", route="oral", stage="GLP target animal safety (TAS)", owner="Program lead (demo)",
             priority="high", jurisdictions=["US", "EU"], keywords=["canine mast cell tumor", "kinase inhibitor"], confirmed=True),
        dict(code="HX-205", name="Hypothetical Program Beta", description="HYPOTHETICAL DEMO. Intralesional small molecule for feline oral tumors.",
             therapeutic_area="oncology", indication="oral squamous cell carcinoma", use_type="veterinary", species=["cat"], target="not disclosed (hypothetical)", mechanism="local cytotoxic",
             modality="intralesional small molecule", molecule_category="small_molecule", route="intralesional", stage="Lead optimization and candidate selection", owner="Research lead (demo)",
             priority="medium", jurisdictions=["US", "EU", "JP"], keywords=["feline oral squamous cell carcinoma"], confirmed=True),
        dict(code="HX-310", name="Hypothetical Program Gamma (on hold)", description="HYPOTHETICAL DEMO. Topical cream for equine sarcoids; paused pending partner interest.",
             therapeutic_area="dermatology / oncology", indication="equine sarcoid", use_type="veterinary", species=["horse"], target=None, mechanism=None, modality="topical cream",
             molecule_category="small_molecule", route="topical", stage="Discovery and target validation", owner=None, priority="low", jurisdictions=["EU"], keywords=[], confirmed=False, status="on_hold"),
    ]
    ids = {}
    for p in progs:
        ids[p["code"]] = conn.execute(
            "INSERT INTO programs (code, name, description, therapeutic_area, indication, use_type, species_json, target, mechanism, modality, molecule_category, route, stage_template, stage, status, owner, priority, "
            "jurisdictions_json, key_dates_json, risks, notes, public_keywords_json, profile_confirmed_at, origin, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'veterinary', ?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p["code"], p["name"], p["description"], p["therapeutic_area"], p["indication"], p["use_type"], jdump(p["species"]), p["target"], p["mechanism"], p["modality"], p["molecule_category"],
             p["route"], p["stage"], p.get("status", "active"), p["owner"], p["priority"], jdump(p["jurisdictions"]), jdump([]),
             "Hypothetical risk note: formulation stability uncertain." if p["code"] == "HX-101" else None, "Hypothetical internal note (confidential in real use).",
             jdump(p["keywords"]), now if p["confirmed"] else None, SYN, now, now)).lastrowid
    return ids


def seed_milestones(conn, pid: dict) -> dict:
    now = utc_now()
    ms = [
        ("HX-101", "API synthesis and formulation", "CMC: API process, formulation and stability", "2026-03-01", "2026-07-31", "done", [], False),
        ("HX-101", "GLP target-animal safety study", "GLP target animal safety (TAS)", "2026-08-01", "2026-12-31", "in_progress", ["API synthesis and formulation"], False),
        ("HX-101", "Pilot field efficacy study", "Pilot field efficacy (GCP) - proof of concept", "2027-01-15", "2027-07-31", "planned", ["GLP target-animal safety study"], True),
        ("HX-101", "Pivotal field study go / no-go", "Pivotal field effectiveness study (GCP)", "2027-08-01", "2027-09-30", "planned", ["Pilot field efficacy study"], True),
        ("HX-205", "Lead compound selection", "Lead optimization and candidate selection", "2026-06-01", "2026-09-30", "at_risk", [], False),
        ("HX-205", "Feline PK pilot", "Preclinical pharmacology and target-species PK", "2026-11-01", "2027-03-31", "planned", ["Lead compound selection"], False),
        ("HX-310", "Hit-to-lead review", "Discovery and target validation", "2026-05-01", "2026-08-31", "planned", [], True),
        # appended (keeps earlier ids stable): completed IP and regulatory-engagement milestones
        ("HX-101", "Composition-of-matter patent filed (PCT)", "Patent filing (provisional, then PCT)", "2025-11-01", "2026-01-31", "done", [], True),
        ("HX-101", "INAD opened and pre-submission conference", "Regulatory engagement (INAD, pre-submission conference, scientific advice)", "2026-02-01", "2026-04-30", "done", [], True),
        ("HX-205", "Provisional patent application filed", "Patent filing (provisional, then PCT)", "2026-04-01", "2026-05-31", "done", [], False),
    ]
    ids: dict[str, int] = {}
    for i, (code, name, stage, s, e, status, deps, decision) in enumerate(ms):
        dep_ids = [ids[d] for d in deps]
        ids[name] = conn.execute(
            "INSERT INTO milestones (program_id, name, stage, planned_start, planned_end, baseline_start, baseline_end, actual_end, status, owner, is_decision_point, depends_on_json, sort_order, origin, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid[code], name, stage, s, e, s, e, e if status == "done" else None, status, "Demo owner", int(decision), jdump(dep_ids), i, SYN, now, now)).lastrowid
    # the lead-selection milestone has slipped vs. its baseline
    conn.execute("UPDATE milestones SET baseline_end = '2026-08-31' WHERE id = ?", (ids["Lead compound selection"],))
    return ids


def _sched(start: str, months: int, total: int) -> dict:
    from ..finance.calc import add_months, month_key, parse_month

    base, rem = divmod(total, months)
    out = {}
    for i in range(months):
        out[month_key(add_months(parse_month(start), i))] = base + (1 if i < rem else 0)
    return out


def seed_finance(conn, pid: dict, mid: dict) -> None:
    now = utc_now()
    ents = {}
    for name, ccy in (("Demo Vet Oncology HK Ltd (synthetic)", "HKD"), ("Demo Vet Oncology Shenzhen Co (synthetic)", "CNY"), ("Demo Vet Oncology US Inc (synthetic)", "USD")):
        ents[ccy] = conn.execute("INSERT INTO legal_entities (name, base_currency) VALUES (?, ?)", (name, ccy)).lastrowid
    accs = {}
    for name, ccy in (("HK operating account (HKD)", "HKD"), ("Shenzhen operating account (CNY)", "CNY"), ("US operating account (USD)", "USD")):
        accs[ccy] = conn.execute("INSERT INTO cash_accounts (name, legal_entity_id, currency, origin) VALUES (?,?,?,?)", (name, ents[ccy], ccy, SYN)).lastrowid
    for ccy, bal in (("HKD", 6_200_000), ("CNY", 1_450_000), ("USD", 380_000)):
        conn.execute("INSERT INTO cash_balances (account_id, as_of_date, balance_minor, currency, source, origin, created_at) VALUES (?,?,?,?,?,?,?)",
                     (accs[ccy], "2026-08-31", _m(bal), ccy, "Synthetic bank statement 2026-08-31", SYN, now))
    for base, quote, rate, d in (("USD", "HKD", "7.7800", "2026-06-30"), ("USD", "CNY", "7.1200", "2026-06-30"), ("USD", "HKD", "7.7750", "2026-09-30"), ("USD", "CNY", "7.0900", "2026-09-30")):
        conn.execute("INSERT INTO fx_rates (base, quote, rate, rate_date, source, method, created_at) VALUES (?,?,?,?,?, 'fixture', ?)",
                     (base, quote, rate, d, "Synthetic demo rate (not market data)", now))
    lines = [
        # program, milestone, category, ccy, planned, approved, contingency%, schedule start, months, source, assumption
        ("HX-101", "API synthesis and formulation", "Manufacturing / CMC", "USD", 180_000, 180_000, 0, "2026-03", 5, "Synthetic CMO quote", "Closed: work complete."),
        ("HX-101", "GLP target-animal safety study", "CRO services", "USD", 320_000, 300_000, 10, "2026-08", 5, "Synthetic CRO proposal v2", "Assumes 24 dogs, 3 dose groups (illustrative)."),
        ("HX-101", "GLP target-animal safety study", "Analytical work", "CNY", 600_000, 600_000, 5, "2026-09", 4, "Internal estimate (synthetic)", "Bioanalytical assay transfer to CRO."),
        ("HX-101", "Pilot field efficacy study", "Clinical / field studies", "USD", 450_000, None, 15, "2027-02", 6, "Planning assumption (synthetic)", "Unapproved estimate: 30 client-owned dogs across 4 sites."),
        ("HX-101", "Pilot field efficacy study", "Manufacturing / CMC", "USD", 220_000, None, 10, "2026-12", 3, "Planning assumption (synthetic)", "Pilot-scale tablet batch."),
        ("HX-205", "Lead compound selection", "Research", "HKD", 900_000, 800_000, 0, "2026-06", 4, "Internal estimate (synthetic)", "Compound synthesis and screening."),
        ("HX-205", "Feline PK pilot", "CRO services", "USD", 140_000, 140_000, 10, "2026-11", 5, "Synthetic CRO quote", "8 cats, single dose."),
        (None, None, "Personnel", "HKD", 3_600_000, 3_600_000, 0, "2026-07", 12, "Payroll plan (synthetic)", "Company-wide team cost."),
        (None, None, "Facilities", "CNY", 720_000, 720_000, 0, "2026-07", 12, "Lease (synthetic)", "Shared lab lease, Shenzhen."),
        (None, None, "Overhead", "USD", 96_000, 96_000, 0, "2026-07", 12, "Budget (synthetic)", "Insurance, software, legal, audit."),
    ]
    for code, ms, cat, ccy, planned, approved, cont, start, months, src, assumption in lines:
        status = "closed" if ms == "API synthesis and formulation" else ("approved" if approved is not None else "draft")
        lid = conn.execute(
            "INSERT INTO budget_lines (program_id, milestone_id, category, description, currency, planned_minor, approved_minor, contingency_bps, owner, estimate_source, assumptions, status, approved_at, origin, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid[code] if code else None, mid[ms] if ms else None, cat, f"{cat} (synthetic)", ccy, _m(planned), _m(approved) if approved is not None else None, cont * 100, "Demo owner",
             src, f"Planning assumption, synthetic: {assumption}", status, now if approved is not None else None, SYN, now, now)).lastrowid
        for month, amt in _sched(start, months, _m(planned)).items():
            conn.execute("INSERT INTO budget_schedule (budget_line_id, month, amount_minor) VALUES (?,?,?)", (lid, month, amt))
    # historical transactions Jul-Oct 2026 (some after the 2026-08-31 reconciliation)
    txns = [
        ("2026-07-05", "HKD", 300_000, "outflow", "operating", "Payroll July", "Personnel", None, None, "shared"),
        ("2026-07-10", "USD", 36_000, "outflow", "operating", "CDMO final invoice", "Manufacturing / CMC", "HX-101", "API synthesis and formulation", "direct"),
        ("2026-07-15", "CNY", 60_000, "outflow", "operating", "Lab lease July", "Facilities", None, None, "shared"),
        ("2026-07-20", "HKD", 210_000, "outflow", "operating", "Screening reagents", "Research", "HX-205", "Lead compound selection", "direct"),
        ("2026-08-05", "HKD", 300_000, "outflow", "operating", "Payroll August", "Personnel", None, None, "shared"),
        ("2026-08-12", "USD", 64_000, "outflow", "operating", "GLP study deposit (CRO)", "CRO services", "HX-101", "GLP target-animal safety study", "direct"),
        ("2026-08-15", "CNY", 60_000, "outflow", "operating", "Lab lease August", "Facilities", None, None, "shared"),
        ("2026-08-20", "USD", 8_000, "outflow", "operating", "Insurance and software", "Overhead", None, None, "shared"),
        ("2026-08-25", "HKD", 260_000, "outflow", "operating", "Screening reagents", "Research", "HX-205", "Lead compound selection", "direct"),
        ("2026-08-28", "USD", 1_500_000, "inflow", "financing", "Seed extension tranche (synthetic)", None, None, None, "unallocated"),
    ]
    for d, ccy, amt, direction, kind, desc, cat, code, ms, alloc in txns:
        conn.execute(
            "INSERT INTO transactions (txn_date, amount_minor, currency, direction, kind, counterparty, description, category, program_id, milestone_id, allocation, legal_entity, account_id, original_json, dedupe_hash, origin, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, _m(amt), ccy, direction, kind, "Synthetic counterparty", desc, cat, pid[code] if code else None, mid[ms] if ms else None, alloc,
             None, accs[ccy], jdump({"note": "synthetic seed"}), f"seed-{d}-{amt}-{desc}", SYN, now))
    conn.execute("INSERT INTO commitments (program_id, milestone_id, category, counterparty, description, currency, amount_minor, expected_payment_date, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (pid["HX-101"], mid["GLP target-animal safety study"], "CRO services", "Demo CRO Ltd", "GLP study milestone 2 invoice (synthetic)", "USD", _m(96_000), "2026-11-15", SYN, now))
    conn.execute("INSERT INTO commitments (program_id, milestone_id, category, counterparty, description, currency, amount_minor, expected_payment_date, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (pid["HX-205"], mid["Feline PK pilot"], "CRO services", "Demo Feline CRO", "PK pilot start-up fee (synthetic)", "USD", _m(28_000), "2026-11-30", SYN, now))
    conn.execute("INSERT INTO planned_flows (label, flow_date, amount_minor, currency, direction, kind, certainty, origin, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 ("Possible Series A first close (hypothetical, synthetic)", "2027-06-30", _m(4_000_000), "USD", "inflow", "financing", "hypothetical", SYN, now))
    conn.execute("INSERT INTO allocation_rules (name, category, shares_json, note, created_at) VALUES (?,?,?,?,?)",
                 ("Shenzhen lab space (synthetic)", "Facilities", jdump({str(pid["HX-101"]): 6000, str(pid["HX-205"]): 4000}), "Allocated by bench-space share (illustrative).", now))
    for kind, name, desc, a in (
        ("base", "Base (approved plan)", "Approved baseline: no changes.", {}),
        ("accelerated", "Accelerated", "Illustrative: unstarted milestones start 2 months earlier; CRO and field-study costs +10%.", {"shift_unstarted_months": -2, "category_cost_change_pct": {"CRO services": 10, "Clinical / field studies": 10}}),
        ("conservative", "Conservative", "Illustrative: unstarted milestones slip 3 months; CRO, CMC and field-study costs +20%.", {"shift_unstarted_months": 3, "category_cost_change_pct": {"CRO services": 20, "Manufacturing / CMC": 20, "Clinical / field studies": 20}}),
        ("custom", "Pilot study starts 3 months later", "Delay the HX-101 pilot field study by 3 months.", {"milestone_shifts": {str(mid["Pilot field efficacy study"]): 3}}),
        ("custom", "Series A closes June 2027 (hypothetical)", "Include the hypothetical financing inflow.", {"include_hypothetical_planned_flows": True}),
    ):
        conn.execute("INSERT INTO scenarios (name, kind, description, assumptions_json, origin, created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (name, kind, desc, jdump(a), SYN, now, now))
    set_setting(conn, "reporting_currency", "USD")
    set_setting(conn, "min_reserve_minor", str(_m(250_000)))
    set_setting(conn, "burn_period_months", "3")
    set_setting(conn, "horizon_months", "18")
    set_setting(conn, "company_name", "Demo Vet Oncology")
    set_setting(conn, "confidential_terms", "Demo Vet Oncology")


def seed_competitors(conn, pid: dict) -> None:
    now = utc_now()
    for code, company, product, ind, mech, mod, geo, stage, note in (
        ("HX-101", "Fixture Animal Health Co. (synthetic)", "FX-KI tablet (synthetic)", "canine mast cell tumor", "kinase inhibition", "small molecule", "US", "pilot study", "Synthetic competitor for demo."),
        ("HX-205", "Example Vet Biologics (synthetic)", "EVB-gel (synthetic)", "feline oral tumor", "local cytotoxic", "intralesional gel", "EU", "preclinical", "Synthetic competitor for demo."),
        ("HX-310", "Sample Equine Therapeutics (synthetic)", "SET-cream (synthetic)", "equine sarcoid", "topical cytotoxic", "cream", "EU", "marketed", "Synthetic competitor for demo."),
    ):
        conn.execute("INSERT INTO competitors (program_id, company, product, species_json, indication, mechanism, modality, geography, stage, status, notes, origin, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?, 'tracked', ?, ?, ?, ?)",
                     (pid[code], company, product, jdump({"HX-101": ["dog"], "HX-205": ["cat"]}.get(code, ["horse"])), ind, mech, mod, geo, stage, note, SYN, now, now))
    conn.execute("INSERT INTO actions (title, detail, program_id, owner, priority, due_date, status, created_by, origin, created_at, updated_at) VALUES (?,?,?,?,?,?, 'open', 'user', ?, ?, ?)",
                 ("Confirm the target-animal safety study design with FDA CVM for HX-101", "Hypothetical action: request a pre-submission meeting before the pilot study.", pid["HX-101"], "Regulatory lead (demo)", "high", "2026-11-20", SYN, now, now))


def seed_all(conn) -> dict:
    migrate(conn)
    seed_registry(conn)
    pid = seed_programs(conn)
    mid = seed_milestones(conn, pid)
    seed_finance(conn, pid, mid)
    seed_competitors(conn, pid)
    set_setting(conn, "as_of_override", AS_OF)
    set_setting(conn, "workspace_label", "Synthetic demonstration data")
    log_activity(conn, "seed", "workspace", None, {"note": "synthetic demo data loaded", "as_of": AS_OF}, actor="system")
    conn.commit()
    return {"programs": pid, "milestones": mid}


def reset_demo_db() -> None:
    path = get_settings().database_path
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    init_db()
    conn = connect()
    try:
        seed_all(conn)
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--into-current", action="store_true", help="add synthetic records to the configured database instead of resetting the demo DB")
    args = ap.parse_args(argv)
    s = get_settings()
    if args.into_current:
        conn = connect()
        try:
            migrate(conn)
            if conn.execute("SELECT COUNT(*) FROM programs").fetchone()[0]:
                print("Database already has programs; refusing to mix synthetic data into it.", file=sys.stderr)
                return 1
            seed_all(conn)
            conn.execute("DELETE FROM app_settings WHERE key = 'as_of_override'")  # live demo uses today's date
            conn.commit()
        finally:
            conn.close()
        print(f"Synthetic records added to {s.database_path}")
        return 0
    if not s.is_demo and "demo" not in s.database_path.name:
        print("Refusing to reset a non-demo database. Use APP_MODE=demo or --into-current with an empty DB.", file=sys.stderr)
        return 1
    reset_demo_db()
    print(f"Demo database reset with synthetic data: {s.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
