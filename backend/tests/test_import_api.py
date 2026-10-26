from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data" / "synthetic_ledger_multi_entity.xlsx"


def test_import_preview_commit_reverse():
    with TestClient(app) as c:
        c.post("/api/demo/reset")
        before = c.get("/api/finance/summary").json()
        up = c.post("/api/imports", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert up.status_code == 201, up.text
        b = up.json()["batch"]
        assert b["sheets"] == ["README", "Transactions"]
        cfg = c.post(f"/api/imports/{b['id']}/configure", json={"sheet": "Transactions", "header_row": 1, "options": {"date_preference": "dmy"}})
        assert cfg.status_code == 200, cfg.text
        data = cfg.json()
        summ = data["batch"]["summary"]
        assert summ["rows_total"] == 19 and summ["rows_duplicate"] == 1 and summ["rows_with_errors"] >= 1
        cro = next(r for r in data["staged"] if r["parsed"] and r["parsed"]["counterparty"] == "Demo CRO Ltd")
        assert cro["parsed"]["commitment_id"] is not None
        kinds = {r["parsed"]["kind"] for r in data["staged"] if r["parsed"]}
        assert {"transfer", "refund", "operating"} <= kinds
        # committing requires explicit confirmation
        assert c.post(f"/api/imports/{b['id']}/commit", json={"confirm": False}).status_code == 422
        com = c.post(f"/api/imports/{b['id']}/commit", json={"confirm": True}).json()
        assert com["batch"]["summary"]["committed_transactions"] == summ["rows_included"]
        assert com["batch"]["summary"]["commitments_marked_paid"] == 1
        after = c.get("/api/finance/summary").json()
        assert after["cash"]["available_cash_minor"] != before["cash"]["available_cash_minor"]
        assert after["burn"]["intercompany"]["pairs"], "cross-currency transfer pair should match"
        # re-uploading the same file is detected; rows are duplicates
        up2 = c.post("/api/imports", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "application/octet-stream")}).json()
        assert any("already committed" in w for w in up2["warnings"])
        cfg2 = c.post(f"/api/imports/{up2['batch']['id']}/configure", json={"sheet": "Transactions"}).json()
        assert cfg2["batch"]["summary"]["rows_included"] == 0
        # reverse keeps audit history
        rev = c.post(f"/api/imports/{b['id']}/reverse", json={"reason": "test reversal"}).json()
        assert rev["transactions_reversed"] == summ["rows_included"] and rev["commitments_reopened"] == 1
        restored = c.get("/api/finance/summary").json()
        assert restored["cash"]["available_cash_minor"] == before["cash"]["available_cash_minor"]
        allt = c.get(f"/api/finance/transactions?batch_id={b['id']}&include_reversed=true").json()
        assert len(allt) == summ["rows_included"] and all(t["reversed"] for t in allt)
        assert allt[0]["original"]["row"], "original row values preserved"
        acts = c.get("/api/activity?entity_type=import_batch").json()
        assert {"upload", "validate", "commit", "reverse"} <= {a["action"] for a in acts}
