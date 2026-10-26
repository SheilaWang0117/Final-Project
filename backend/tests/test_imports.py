from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from app.finance import imports
from app.finance.imports import Context, ImportError_


def ctx(**kw):
    base = dict(
        programs=[{"id": 1, "code": "HX-101", "name": "Hypothetical Program Alpha"}],
        milestones=[{"id": 10, "program_id": 1, "name": "GLP tox study"}],
        accounts=[{"id": 1, "name": "HSBC HKD", "currency": "HKD", "legal_entity": "Demo HK Ltd"}],
        existing_hashes=set(),
        open_commitments=[{"id": 5, "counterparty": "Demo CRO Ltd", "amount_minor": 1500000, "currency": "HKD"}],
        counterparty_history={},
    )
    base.update(kw)
    return Context(**base)


CSV = (
    "Date,Description,Counterparty,Amount,Currency,Program,Account\n"
    "2026-07-03,HX-101 GLP tox study deposit,Demo CRO Ltd,\"-15,000.00\",HKD,,HSBC HKD\n"
    "04/07/2026,Office rent July,Landlord Co,-30000,HKD,,HSBC HKD\n"
    "2026-07-05,Refund of reagent overcharge,Reagent Supplier,1200.50,HKD,HX-101,HSBC HKD\n"
    "2026-07-06,Series A tranche,Investor LP,\"2,000,000\",HKD,,HSBC HKD\n"
    "2026-07-07,Transfer to USD account,Own account,-50000,HKD,,HSBC HKD\n"
    "2026-07-08,Unknown thing,Someone,abc,HKD,,HSBC HKD\n"
    "2026-07-03,HX-101 GLP tox study deposit,Demo CRO Ltd,\"-15,000.00\",HKD,,HSBC HKD\n"
    "2026-07-09,Mystery,Someone,-10,XYZ,,HSBC HKD\n"
)


def stage(data=CSV, **kw):
    parsed = imports.parse_file("bank.csv", data.encode())
    mapping = imports.guess_mapping(parsed.rows[0])
    return imports.validate_rows(parsed.rows, 1, mapping, {"default_currency": "HKD"}, ctx(**kw))


def test_guess_mapping():
    m = imports.guess_mapping(["Date", "Description", "Counterparty", "Amount", "Currency", "Program", "Account"])
    assert m == {"txn_date": 0, "description": 1, "counterparty": 2, "amount": 3, "currency": 4, "program": 5, "account": 6}


def test_validation_flags_and_suggestions():
    rows, summary = stage()
    by_row = {r["sheet_row"]: r for r in rows}
    cro = by_row[2]
    assert cro["parsed"]["amount_minor"] == 1500000 and cro["parsed"]["direction"] == "outflow"
    assert cro["parsed"]["program_id"] == 1 and cro["parsed"]["milestone_id"] == 10
    assert cro["parsed"]["category"] == "Preclinical studies" or cro["parsed"]["category"] == "CRO services"
    assert cro["parsed"]["commitment_id"] == 5
    rent = by_row[3]
    assert any("ambiguous day/month" in i["message"] for i in rent["issues"])
    assert rent["parsed"]["allocation"] == "shared"
    assert by_row[4]["parsed"]["kind"] == "refund"
    assert by_row[5]["parsed"]["kind"] == "financing"
    assert by_row[6]["parsed"]["kind"] == "transfer"
    assert by_row[7]["parsed"] is None and by_row[7]["decision"] == "skip"
    assert any(i["level"] == "duplicate" for i in by_row[8]["issues"]) and by_row[8]["decision"] == "skip"
    assert by_row[9]["decision"] == "skip"
    assert summary["rows_total"] == 8 and summary["rows_included"] == 5
    assert "never combined" in summary["note"]


def test_reimport_detected_as_duplicate():
    rows, _ = stage()
    hashes = {r["parsed"]["dedupe_hash"] for r in rows if r["parsed"]}
    rows2, summary2 = stage(existing_hashes=hashes)
    assert summary2["rows_included"] == 0


def test_statement_check():
    rows, _ = stage()
    s = imports.summarize(rows, {"account_id": 1, "opening_minor": 0, "closing_minor": 0})
    assert s["statement_check"]["reconciled"] is False


def test_xlsx_formula_not_executed_and_sheet_selection():
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes"
    ws.append(["ignore me"])
    ws2 = wb.create_sheet("Ledger")
    ws2.append(["Date", "Description", "Amount", "Currency"])
    ws2.append(["2026-07-01", "Formula row", "=1+1", "USD"])
    ws2.append(["2026-07-02", "=HYPERLINK(\"http://evil\",\"x\")", -25.5, "USD"])
    buf = io.BytesIO()
    wb.save(buf)
    parsed = imports.parse_file("ledger.xlsx", buf.getvalue(), sheet="Ledger")
    assert parsed.sheets == ["Notes", "Ledger"] and parsed.sheet == "Ledger"
    mapping = imports.guess_mapping(parsed.rows[0])
    rows, summary = imports.validate_rows(parsed.rows, 1, mapping, {}, ctx())
    # formula cell has no cached value -> no amount, never evaluated
    assert rows[0]["parsed"] is None
    assert rows[1]["parsed"]["amount_minor"] == 2550
    assert rows[1]["parsed"]["description"] is None  # HYPERLINK formula not evaluated


def test_formula_looking_text_flagged():
    data = "Date,Description,Amount,Currency\n2026-07-02,=HYPERLINK(\"http://evil\"),-5,USD\n"
    parsed = imports.parse_file("x.csv", data.encode())
    rows, _ = imports.validate_rows(parsed.rows, 1, imports.guess_mapping(parsed.rows[0]), {}, ctx())
    assert any("formula" in i["message"] for i in rows[0]["issues"])


def test_rejects_macro_and_unknown_files():
    with pytest.raises(ImportError_):
        imports.parse_file("evil.xlsm", b"PK\x03\x04")
    with pytest.raises(ImportError_):
        imports.parse_file("x.exe", b"MZ")
    with pytest.raises(ImportError_):
        imports.parse_file("big.csv", b"a" * 20, max_bytes=10)


def test_csv_export_formula_injection_protection():
    out = imports.to_csv(["name"], [["=cmd|' /C calc'!A0"], ["@SUM(1)"], ["normal"], [-5]])
    lines = out.strip().splitlines()
    assert lines[1].startswith("\"'=") or lines[1].startswith("'=")
    assert lines[2].startswith("'@")
    assert lines[3] == "normal"
    assert lines[4] == "-5"


def test_assay_transfer_is_not_a_cash_transfer():
    assert imports.suggest_kind("Bioanalytical assay transfer")[0] is None
    assert imports.suggest_kind("Technology transfer fee")[0] is None
    assert imports.suggest_kind("Intercompany transfer to US entity")[0] == "transfer"
    assert imports.suggest_kind("Transfer from HK account")[0] == "transfer"
