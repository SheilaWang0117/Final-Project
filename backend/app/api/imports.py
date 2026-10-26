"""Reviewable CSV/XLSX import workflow.

upload -> preview & sheet selection -> column mapping -> validation (dates,
currencies, amounts, duplicates, ambiguity) -> suggestions -> reconciliation
summary -> explicit commit. Batches can be reversed; reversal flags the
transactions instead of deleting them, so the audit history is preserved.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import REPO_ROOT, get_settings
from ..db import get_conn, jdump, jload, log_activity, rows, utc_now
from ..finance import imports as imp

router = APIRouter(prefix="/api/imports", tags=["imports"])
UPLOAD_DIR = REPO_ROOT / "data" / "uploads"
SAMPLE_DIR = REPO_ROOT / "sample_data"


class ConfigureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str | None = None
    header_row: int = Field(default=1, ge=1, le=50)
    mapping: dict[str, int] | None = None
    options: dict = Field(default_factory=dict)


class RowEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str | None = Field(default=None, pattern="^(include|skip)$")
    category: str | None = None
    program_id: int | None = None
    milestone_id: int | None = None
    kind: str | None = Field(default=None, pattern="^(operating|refund|financing|transfer)$")
    allocation: str | None = Field(default=None, pattern="^(direct|shared|unallocated)$")
    account_id: int | None = None
    commitment_id: int | None = None
    clear_commitment: bool = False


class CommitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    statement: dict | None = None


class ReverseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


def _batch(conn, bid: int) -> dict:
    r = conn.execute("SELECT * FROM import_batches WHERE id = ?", (bid,)).fetchone()
    if not r:
        raise HTTPException(404, "Import batch not found")
    d = dict(r)
    for k in ("sheets_json", "mapping_json", "options_json", "summary_json"):
        d[k.replace("_json", "")] = jload(d.pop(k), {} if k != "sheets_json" else [])
    return d


def _context(conn) -> imp.Context:
    hist: dict[str, dict] = {}
    for r in conn.execute("SELECT counterparty, category, program_id FROM transactions WHERE reversed = 0 AND counterparty IS NOT NULL ORDER BY id"):
        hist[imp._norm(r["counterparty"])] = {"category": r["category"], "program_id": r["program_id"]}
    return imp.Context(
        programs=rows(conn.execute("SELECT id, code, name FROM programs WHERE archived = 0").fetchall()),
        milestones=rows(conn.execute("SELECT id, program_id, name FROM milestones").fetchall()),
        accounts=rows(conn.execute("SELECT a.id, a.name, a.currency, e.name AS legal_entity FROM cash_accounts a LEFT JOIN legal_entities e ON e.id = a.legal_entity_id").fetchall()),
        existing_hashes={r[0] for r in conn.execute("SELECT dedupe_hash FROM transactions WHERE reversed = 0")},
        open_commitments=rows(conn.execute("SELECT id, counterparty, amount_minor, currency FROM commitments WHERE status = 'open'").fetchall()),
        counterparty_history=hist,
    )


def _store_rows(conn, bid: int, parsed: imp.ParsedFile):
    conn.execute("DELETE FROM import_rows WHERE batch_id = ?", (bid,))
    for i, r in enumerate(parsed.rows, start=1):
        conn.execute("INSERT INTO import_rows (batch_id, sheet_row, raw_json) VALUES (?,?,?)", (bid, i, jdump(r)))


def _all_rows(conn, bid: int) -> list[list[str]]:
    out = []
    for r in conn.execute("SELECT sheet_row, raw_json FROM import_rows WHERE batch_id = ? ORDER BY sheet_row", (bid,)):
        while len(out) < r["sheet_row"] - 1:
            out.append([])
        out.append(jload(r["raw_json"], []))
    return out


@router.get("")
def list_batches(conn=Depends(get_conn)):
    out = []
    for r in conn.execute("SELECT id FROM import_batches ORDER BY id DESC"):
        b = _batch(conn, r["id"])
        b["transactions"] = conn.execute("SELECT COUNT(*) FROM transactions WHERE batch_id = ?", (r["id"],)).fetchone()[0]
        out.append(b)
    return out


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), conn=Depends(get_conn)):
    s = get_settings()
    data = await file.read(s.upload_max_bytes + 1)
    if len(data) > s.upload_max_bytes:
        raise HTTPException(413, f"File exceeds {s.upload_max_bytes // (1024 * 1024)} MB")
    name = Path(file.filename or "upload").name[:200]
    try:
        parsed = imp.parse_file(name, data, max_rows=s.import_max_rows, max_bytes=s.upload_max_bytes)
    except imp.ImportError_ as exc:
        raise HTTPException(422, str(exc))
    digest = imp.sha256(data)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / f"{digest}.{parsed.file_type}").write_bytes(data)
    prior = conn.execute("SELECT id, status FROM import_batches WHERE file_sha256 = ? AND status = 'committed'", (digest,)).fetchone()
    header = parsed.rows[0] if parsed.rows else []
    mapping = imp.guess_mapping(header)
    bid = conn.execute(
        "INSERT INTO import_batches (filename, file_sha256, file_type, sheet_name, sheets_json, mapping_json, created_at) VALUES (?,?,?,?,?,?,?)",
        (name, digest, parsed.file_type, parsed.sheet, jdump(parsed.sheets), jdump(mapping), utc_now()),
    ).lastrowid
    _store_rows(conn, bid, parsed)
    log_activity(conn, "upload", "import_batch", bid, {"filename": name, "sha256": digest[:12], "rows": len(parsed.rows)})
    return {
        "batch": _batch(conn, bid),
        "preview": parsed.rows[:25],
        "warnings": parsed.warnings + ([f"This exact file was already committed in batch #{prior['id']}."] if prior else []),
        "fields": imp.FIELDS,
    }


@router.get("/{bid}")
def get_batch(bid: int, conn=Depends(get_conn)):
    b = _batch(conn, bid)
    all_rows = _all_rows(conn, bid)
    return {"batch": b, "preview": all_rows[:25], "staged": _staged(conn, bid), "fields": imp.FIELDS}


def _row_out(r) -> dict:
    return {"id": r["id"], "sheet_row": r["sheet_row"], "raw": jload(r["raw_json"], []), "parsed": jload(r["parsed_json"], None),
            "issues": jload(r["issues_json"], []), "suggestion": jload(r["suggestion_json"], {}), "decision": r["decision"]}


@router.post("/{bid}/configure")
def configure(bid: int, body: ConfigureIn, conn=Depends(get_conn)):
    b = _batch(conn, bid)
    if b["status"] in ("committed", "reversed", "discarded"):
        raise HTTPException(409, f"Batch is {b['status']}")
    if body.sheet and body.sheet != b["sheet_name"]:
        path = UPLOAD_DIR / f"{b['file_sha256']}.{b['file_type']}"
        if not path.exists():
            raise HTTPException(410, "Original upload no longer available; upload again")
        try:
            parsed = imp.parse_file(b["filename"], path.read_bytes(), sheet=body.sheet, max_rows=get_settings().import_max_rows)
        except imp.ImportError_ as exc:
            raise HTTPException(422, str(exc))
        _store_rows(conn, bid, parsed)
        conn.execute("UPDATE import_batches SET sheet_name = ? WHERE id = ?", (parsed.sheet, bid))
    all_rows = _all_rows(conn, bid)
    if body.header_row > len(all_rows):
        raise HTTPException(422, "Header row is beyond the end of the sheet")
    mapping = body.mapping if body.mapping is not None else imp.guess_mapping(all_rows[body.header_row - 1])
    bad = [k for k in mapping if k not in imp.FIELDS]
    if bad:
        raise HTTPException(422, f"Unknown fields in mapping: {bad}")
    try:
        staged, summary = imp.validate_rows(all_rows, body.header_row, mapping, body.options, _context(conn))
    except imp.ImportError_ as exc:
        raise HTTPException(422, str(exc))
    conn.execute("UPDATE import_rows SET parsed_json = NULL, issues_json = '[]', suggestion_json = '{}', decision = 'skip' WHERE batch_id = ?", (bid,))
    for s in staged:
        conn.execute(
            "UPDATE import_rows SET parsed_json = ?, issues_json = ?, suggestion_json = ?, decision = ? WHERE batch_id = ? AND sheet_row = ?",
            (jdump(s["parsed"]) if s["parsed"] else None, jdump(s["issues"]), jdump(s["suggestion"]), s["decision"], bid, s["sheet_row"]),
        )
    conn.execute("UPDATE import_batches SET header_row = ?, mapping_json = ?, options_json = ?, status = 'validated', summary_json = ? WHERE id = ?",
                 (body.header_row, jdump(mapping), jdump(body.options), jdump(summary), bid))
    log_activity(conn, "validate", "import_batch", bid, {"rows": summary["rows_total"], "errors": summary["rows_with_errors"], "duplicates": summary["rows_duplicate"]})
    return get_batch(bid, conn)


def _staged(conn, bid) -> list[dict]:
    return [_row_out(r) for r in conn.execute("SELECT * FROM import_rows WHERE batch_id = ? AND (parsed_json IS NOT NULL OR issues_json != '[]') ORDER BY sheet_row", (bid,))]


@router.patch("/{bid}/rows/{row_id}")
def edit_row(bid: int, row_id: int, body: RowEdit, conn=Depends(get_conn)):
    b = _batch(conn, bid)
    if b["status"] != "validated":
        raise HTTPException(409, "Only validated batches can be edited")
    r = conn.execute("SELECT * FROM import_rows WHERE id = ? AND batch_id = ?", (row_id, bid)).fetchone()
    if not r:
        raise HTTPException(404, "Row not found")
    parsed = jload(r["parsed_json"], None)
    edits = body.model_dump(exclude_unset=True)
    decision = edits.pop("decision", None)
    if decision == "include" and not parsed:
        raise HTTPException(422, "Rows with errors cannot be included; fix the source file or mapping")
    if parsed:
        if edits.pop("clear_commitment", False):
            parsed["commitment_id"] = None
        for k, v in edits.items():
            parsed[k] = v
        if edits.get("program_id") and "allocation" not in edits:
            parsed["allocation"] = "direct"
        if edits.get("milestone_id"):
            m = conn.execute("SELECT program_id FROM milestones WHERE id = ?", (edits["milestone_id"],)).fetchone()
            if not m:
                raise HTTPException(422, "Milestone not found")
            parsed["program_id"] = m["program_id"]
            parsed["allocation"] = "direct"
    conn.execute("UPDATE import_rows SET parsed_json = ?, decision = COALESCE(?, decision) WHERE id = ?", (jdump(parsed) if parsed else None, decision, row_id))
    summary = imp.summarize(_staged(conn, bid))
    conn.execute("UPDATE import_batches SET summary_json = ? WHERE id = ?", (jdump(summary), bid))
    return {"row": _row_out(conn.execute("SELECT * FROM import_rows WHERE id = ?", (row_id,)).fetchone()), "summary": summary}


@router.post("/{bid}/reconcile")
def reconcile(bid: int, statement: dict, conn=Depends(get_conn)):
    """Optional bank statement check: opening + imported movement = closing."""
    _batch(conn, bid)
    from ..finance.money import to_minor
    from decimal import Decimal, InvalidOperation

    try:
        acc = conn.execute("SELECT currency FROM cash_accounts WHERE id = ?", (int(statement["account_id"]),)).fetchone()
        if not acc:
            raise HTTPException(404, "Account not found")
        st = {"account_id": int(statement["account_id"]),
              "opening_minor": to_minor(Decimal(str(statement["opening"])), acc["currency"]),
              "closing_minor": to_minor(Decimal(str(statement["closing"])), acc["currency"])}
    except (KeyError, InvalidOperation, ValueError):
        raise HTTPException(422, "Provide account_id, opening and closing")
    summary = imp.summarize(_staged(conn, bid), st)
    conn.execute("UPDATE import_batches SET summary_json = ? WHERE id = ?", (jdump(summary), bid))
    return summary


@router.post("/{bid}/commit")
def commit(bid: int, body: CommitIn, conn=Depends(get_conn)):
    if not body.confirm:
        raise HTTPException(422, "Set confirm=true after reviewing the reconciliation summary")
    b = _batch(conn, bid)
    if b["status"] != "validated":
        raise HTTPException(409, f"Batch is {b['status']}; validate before committing")
    existing = {r[0] for r in conn.execute("SELECT dedupe_hash FROM transactions WHERE reversed = 0")}
    inserted, skipped_dupes, linked = 0, 0, 0
    now = utc_now()
    for r in conn.execute("SELECT * FROM import_rows WHERE batch_id = ? AND decision = 'include' AND parsed_json IS NOT NULL ORDER BY sheet_row", (bid,)).fetchall():
        p = jload(r["parsed_json"], {})
        if p["dedupe_hash"] in existing:
            skipped_dupes += 1
            continue
        existing.add(p["dedupe_hash"])
        original = {"row": jload(r["raw_json"], []), "mapping": b["mapping"], "sheet": b["sheet_name"], "file": b["filename"], "reference": p.get("reference")}
        tid = conn.execute(
            "INSERT INTO transactions (batch_id, source_row, txn_date, amount_minor, currency, direction, kind, counterparty, description, category, program_id, milestone_id, "
            "allocation, legal_entity, account_id, commitment_id, original_json, dedupe_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bid, r["sheet_row"], p["txn_date"], p["amount_minor"], p["currency"], p["direction"], p["kind"], p["counterparty"], p["description"], p["category"],
             p["program_id"], p["milestone_id"], p["allocation"], p["legal_entity"], p["account_id"], p.get("commitment_id"), jdump(original), p["dedupe_hash"], now),
        ).lastrowid
        if p.get("commitment_id"):
            n = conn.execute("UPDATE commitments SET status = 'paid', paid_transaction_id = ? WHERE id = ? AND status = 'open'", (tid, p["commitment_id"])).rowcount
            linked += n
        inserted += 1
    summary = b["summary"] | {"committed_transactions": inserted, "skipped_duplicates_at_commit": skipped_dupes, "commitments_marked_paid": linked}
    conn.execute("UPDATE import_batches SET status = 'committed', committed_at = ?, summary_json = ? WHERE id = ?", (now, jdump(summary), bid))
    log_activity(conn, "commit", "import_batch", bid, {"inserted": inserted, "duplicates_skipped": skipped_dupes, "commitments_paid": linked})
    return {"batch": _batch(conn, bid)}


@router.post("/{bid}/reverse")
def reverse(bid: int, body: ReverseIn, conn=Depends(get_conn)):
    b = _batch(conn, bid)
    if b["status"] != "committed":
        raise HTTPException(409, "Only committed batches can be reversed")
    ids = [r[0] for r in conn.execute("SELECT id FROM transactions WHERE batch_id = ?", (bid,))]
    conn.execute("UPDATE transactions SET reversed = 1 WHERE batch_id = ?", (bid,))
    reopened = 0
    if ids:
        q = ",".join("?" * len(ids))
        reopened = conn.execute(f"UPDATE commitments SET status = 'open', paid_transaction_id = NULL WHERE paid_transaction_id IN ({q})", ids).rowcount
    conn.execute("UPDATE import_batches SET status = 'reversed', reversed_at = ?, reverse_reason = ? WHERE id = ?", (utc_now(), body.reason, bid))
    log_activity(conn, "reverse", "import_batch", bid, {"transactions_flagged_reversed": len(ids), "commitments_reopened": reopened, "reason": body.reason})
    return {"batch": _batch(conn, bid), "transactions_reversed": len(ids), "commitments_reopened": reopened}


@router.post("/{bid}/discard")
def discard(bid: int, conn=Depends(get_conn)):
    b = _batch(conn, bid)
    if b["status"] in ("committed", "reversed"):
        raise HTTPException(409, "Committed batches are reversed, not discarded")
    conn.execute("UPDATE import_batches SET status = 'discarded' WHERE id = ?", (bid,))
    log_activity(conn, "discard", "import_batch", bid)
    return {"ok": True}


TEMPLATES = {
    "transactions_template.csv": "text/csv",
    "transactions_template.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "synthetic_bank_export_hkd.csv": "text/csv",
    "synthetic_ledger_multi_entity.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("/templates/{name}")
def template(name: str):
    if name not in TEMPLATES:
        raise HTTPException(404, "Unknown template")
    path = SAMPLE_DIR / name
    if not path.exists():
        raise HTTPException(404, "Template file missing; run scripts/make_sample_data.py")
    return FileResponse(path, media_type=TEMPLATES[name], filename=name)
