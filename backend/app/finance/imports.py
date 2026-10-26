"""Spreadsheet import: parse, map, validate, suggest, reconcile.

Safety rules:
- Only .csv and .xlsx are accepted, within size and row limits.
- XLSX is read with openpyxl in read-only, data-only mode: cached cell values
  are read, formulas are never evaluated, and macros are never executed.
  Cells that still look like formulas are flagged and not imported as values.
- Nothing is written to the ledger here; commit happens only after review.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .money import SUPPORTED_CURRENCIES, normalize_currency, parse_amount, to_minor

FIELDS = [
    "txn_date", "amount", "debit", "credit", "currency", "direction", "counterparty",
    "description", "category", "program", "milestone", "legal_entity", "account", "kind", "reference",
]
REQUIRED_ANY = [("txn_date",), ("amount", "debit", "credit")]

HEADER_SYNONYMS = {
    "txn_date": ["date", "transaction date", "txn date", "value date", "posting date", "booked", "日期", "交易日期"],
    "amount": ["amount", "value", "sum", "金额", "amount (original)"],
    "debit": ["debit", "withdrawal", "paid out", "money out", "支出", "借方"],
    "credit": ["credit", "deposit", "paid in", "money in", "收入", "贷方"],
    "currency": ["currency", "ccy", "cur", "币种", "货币"],
    "direction": ["direction", "type", "dr/cr", "in/out"],
    "counterparty": ["counterparty", "payee", "vendor", "supplier", "payer", "merchant", "对方", "收款方"],
    "description": ["description", "memo", "details", "narrative", "particulars", "摘要", "备注"],
    "category": ["category", "cost category", "expense type", "类别"],
    "program": ["program", "pipeline", "project", "program code", "项目"],
    "milestone": ["milestone", "workstream", "里程碑"],
    "legal_entity": ["entity", "legal entity", "company", "主体"],
    "account": ["account", "bank account", "account name", "账户"],
    "kind": ["kind", "flow type", "classification"],
    "reference": ["reference", "ref", "invoice", "invoice no", "voucher", "凭证号"],
}

CATEGORIES = [
    "Research", "Preclinical studies", "Manufacturing / CMC", "Analytical work", "Regulatory",
    "Clinical / field studies", "CRO services", "Personnel", "Facilities", "Overhead",
]

CATEGORY_KEYWORDS = {
    "CRO services": ["cro", "contract research", "study fee", "wuxi", "charles river", "labcorp"],
    "Preclinical studies": ["glp", "tox", "toxicology", "pk study", "pharmacokinetic", "safety study", "preclinical"],
    "Manufacturing / CMC": ["cmc", "cdmo", "manufactur", "cell line", "fill finish", "batch", "drug substance", "gmp"],
    "Analytical work": ["assay", "analytical", "elisa", "qc test", "stability", "characterization"],
    "Regulatory": ["regulatory", "filing fee", "submission", "dossier", "consultant - reg", "fda fee", "ind", "inad"],
    "Clinical / field studies": ["clinical", "field study", "trial", "pilot study", "iit", "investigator", "vet hospital", "veterinary hospital"],
    "Research": ["reagent", "antibody discovery", "research", "lab supplies", "consumable"],
    "Personnel": ["salary", "payroll", "bonus", "mpf", "social insurance", "wages", "工资"],
    "Facilities": ["rent", "lease", "utilities", "electricity", "property management", "房租"],
    "Overhead": ["software", "insurance", "legal", "audit fee", "accounting", "travel", "office", "bank charge", "subscription"],
}

KIND_KEYWORDS = {
    # specific phrases only: "assay transfer" or "technology transfer" are operating costs, not cash transfers
    "transfer": ["transfer to", "transfer from", "intercompany", "inter-company", "own account", "fx conversion", "internal transfer", "account transfer", "funds transfer"],
    "financing": ["series a", "seed round", "investment", "capital injection", "share subscription", "convertible", "loan drawdown", "loan proceeds", "safe note", "增资"],
    "refund": ["refund", "rebate", "reimbursement received", "credit note", "returned", "退款"],
}


class ImportError_(ValueError):
    pass


@dataclass
class ParsedFile:
    file_type: str
    sheets: list[str]
    sheet: str | None
    rows: list[list[str]]  # all rows, as text, including header
    warnings: list[str]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_type(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".csv"):
        if b"\x00" in data[:4096]:
            raise ImportError_("CSV contains binary content")
        return "csv"
    if name.endswith(".xlsx"):
        if not data.startswith(b"PK"):
            raise ImportError_("File is not a valid .xlsx workbook")
        return "xlsx"
    if name.endswith((".xlsm", ".xls", ".xlsb")):
        raise ImportError_("Only .xlsx and .csv are accepted. Macro-enabled (.xlsm) and legacy (.xls/.xlsb) workbooks are rejected; save as .xlsx or .csv.")
    raise ImportError_("Unsupported file type; upload .csv or .xlsx")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(v) if not v.is_integer() else str(int(v))
    return str(v)


def parse_file(filename: str, data: bytes, sheet: str | None = None, max_rows: int = 5000, max_bytes: int = 5 * 1024 * 1024) -> ParsedFile:
    if len(data) > max_bytes:
        raise ImportError_(f"File is larger than the {max_bytes // (1024 * 1024)} MB limit")
    ftype = detect_type(filename, data)
    warnings: list[str] = []
    if ftype == "csv":
        text = None
        for enc in ("utf-8-sig", "gb18030", "latin-1"):
            try:
                text = data.decode(enc)
                if enc != "utf-8-sig":
                    warnings.append(f"File decoded as {enc}; check text columns")
                break
            except UnicodeDecodeError:
                continue
        reader = csv.reader(io.StringIO(text or ""))
        rows = []
        for i, r in enumerate(reader):
            if i > max_rows:
                raise ImportError_(f"File has more than {max_rows} rows")
            rows.append([c.strip() for c in r])
        return ParsedFile("csv", [], None, rows, warnings)

    from openpyxl import load_workbook

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                warnings.append("Workbook contains a macro project; macros are ignored and never executed")
            total = sum(i.file_size for i in zf.infolist())
            if total > 60 * 1024 * 1024:
                raise ImportError_("Workbook expands to an unsafe size")
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_vba=False, keep_links=False)
    except ImportError_:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clear message for any malformed workbook
        raise ImportError_(f"Could not read workbook: {type(exc).__name__}") from exc
    sheets = list(wb.sheetnames)
    name = sheet if sheet in sheets else sheets[0]
    ws = wb[name]
    rows = []
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i > max_rows:
            raise ImportError_(f"Sheet has more than {max_rows} rows")
        rows.append([_cell_text(c).strip() for c in r])
    wb.close()
    while rows and not any(rows[-1]):
        rows.pop()
    return ParsedFile("xlsx", sheets, name, rows, warnings)


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿/ ]", "", h.lower()).strip()


def guess_mapping(headers: list[str]) -> dict[str, int]:
    """Map known fields to column indexes using header synonyms (exact, then prefix)."""
    mapping: dict[str, int] = {}
    normed = [_norm(h) for h in headers]
    for field_name, syns in HEADER_SYNONYMS.items():
        for idx, h in enumerate(normed):
            if idx in mapping.values():
                continue
            if h in syns or h == field_name.replace("_", " "):
                mapping[field_name] = idx
                break
    for field_name, syns in HEADER_SYNONYMS.items():
        if field_name in mapping:
            continue
        for idx, h in enumerate(normed):
            if idx in mapping.values():
                continue
            if any(h.startswith(s) for s in syns if len(s) > 3):
                mapping[field_name] = idx
                break
    return mapping


_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"), "ymd"),
    (re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$"), "dmy_or_mdy"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$"), "ymd"),
]


def parse_date(text: str, preference: str = "dmy") -> tuple[date | None, list[str]]:
    t = (text or "").strip()
    if not t:
        return None, ["missing date"]
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        try:
            if kind == "ymd":
                return date(a, b, c), []
            # a/b/yyyy: ambiguous when both parts <= 12 and differ
            issues = []
            if a <= 12 and b <= 12 and a != b:
                issues.append(f"ambiguous day/month order in '{t}' (read as {preference.upper()})")
            if a > 12:
                return date(c, b, a), []
            if b > 12:
                return date(c, a, b), []
            return (date(c, b, a) if preference == "dmy" else date(c, a, b)), issues
        except ValueError:
            return None, [f"invalid date '{t}'"]
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(t, fmt).date(), []
        except ValueError:
            continue
    return None, [f"unrecognized date '{t}'"]


def suggest_category(text: str) -> tuple[str | None, str | None]:
    low = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        for w in words:
            if w in low:
                return cat, f"keyword '{w}'"
    return None, None


def suggest_kind(text: str) -> tuple[str | None, str | None]:
    low = text.lower()
    for kind, words in KIND_KEYWORDS.items():
        for w in words:
            if w in low:
                return kind, f"keyword '{w}'"
    return None, None


def dedupe_hash(d: date, amount_minor: int, currency: str, direction: str, counterparty: str, description: str, reference: str = "") -> str:
    basis = "|".join([d.isoformat(), str(amount_minor), currency, direction, _norm(counterparty or ""), _norm(description or "")[:80], _norm(reference or "")])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


@dataclass
class Context:
    """Reference data used for validation and suggestions (internal only, never sent externally)."""

    programs: list[dict]  # {id, code, name}
    milestones: list[dict]  # {id, program_id, name}
    accounts: list[dict]  # {id, name, currency, legal_entity}
    existing_hashes: set[str]
    open_commitments: list[dict]  # {id, counterparty, amount_minor, currency}
    counterparty_history: dict[str, dict]  # normalized counterparty -> {category, program_id}


def validate_rows(
    rows: list[list[str]],
    header_row: int,
    mapping: dict[str, int],
    options: dict,
    ctx: Context,
) -> tuple[list[dict], dict]:
    """Validate data rows. Returns (staged rows, summary). Pure function."""
    header_idx = header_row - 1
    data = rows[header_idx + 1:]
    default_currency = normalize_currency(options.get("default_currency")) if options.get("default_currency") else None
    date_pref = options.get("date_preference", "dmy")
    sign_convention = options.get("sign_convention", "negative_is_outflow")
    default_account = options.get("default_account_id")
    staged = []
    seen_in_file: dict[str, int] = {}
    missing = [f for group in REQUIRED_ANY if not any(g in mapping for g in group) for f in group[:1]]
    if missing:
        raise ImportError_(f"Map at least one column for: {', '.join(missing)} (and an amount, debit or credit column)")

    def cell(r, key):
        idx = mapping.get(key)
        if idx is None or idx >= len(r):
            return ""
        return r[idx]

    for offset, r in enumerate(data):
        sheet_row = header_idx + 2 + offset
        if not any((c or "").strip() for c in r):
            continue
        raw = {h: (r[i] if i < len(r) else "") for h, i in mapping.items()}
        issues: list[dict] = []

        def flag(level, msg):
            issues.append({"level": level, "message": msg})

        for key, val in raw.items():
            if isinstance(val, str) and val[:1] in ("=", "+", "@") and key not in ("amount", "debit", "credit"):
                flag("warning", f"{key} looks like a spreadsheet formula; imported as plain text")
            if isinstance(val, str) and val.startswith("=") and key in ("amount", "debit", "credit"):
                flag("error", f"{key} is an unevaluated formula; export values, not formulas")
        d, dissues = parse_date(cell(r, "txn_date"), date_pref)
        for m in dissues:
            flag("error" if d is None else "warning", m)

        amount: Decimal | None = None
        direction = None
        cur_hint = None
        if "amount" in mapping and cell(r, "amount"):
            pa = parse_amount(cell(r, "amount"))
            cur_hint = pa.currency_hint
            for m in pa.issues:
                flag("warning" if pa.value is not None else "error", m)
            if pa.value is not None:
                amount = abs(pa.value)
                if pa.value < 0:
                    direction = "outflow" if sign_convention == "negative_is_outflow" else "inflow"
                elif pa.value > 0:
                    direction = "inflow" if sign_convention == "negative_is_outflow" else "outflow"
        else:
            deb = parse_amount(cell(r, "debit")) if cell(r, "debit") else None
            cre = parse_amount(cell(r, "credit")) if cell(r, "credit") else None
            if deb and deb.value and cre and cre.value:
                flag("error", "both debit and credit are filled")
            elif deb and deb.value is not None and deb.value != 0:
                amount, direction, cur_hint = abs(deb.value), "outflow", deb.currency_hint
            elif cre and cre.value is not None and cre.value != 0:
                amount, direction, cur_hint = abs(cre.value), "inflow", cre.currency_hint
            for p in (deb, cre):
                if p:
                    for m in p.issues:
                        flag("warning" if p.value is not None else "error", m)
        dir_text = cell(r, "direction").strip().lower()
        if dir_text:
            explicit = "outflow" if dir_text in ("out", "outflow", "debit", "dr", "payment", "expense", "支出") else "inflow" if dir_text in ("in", "inflow", "credit", "cr", "receipt", "income", "收入") else None
            if explicit is None:
                flag("warning", f"unrecognized direction '{dir_text}'")
            elif direction and explicit != direction and "amount" in mapping:
                # explicit column wins over the sign convention
                direction = explicit
            else:
                direction = explicit or direction
        if amount is None:
            flag("error", "missing or invalid amount")
        elif amount == 0:
            flag("error", "amount is zero")
        if direction is None and amount:
            flag("error", "cannot determine direction (inflow/outflow)")

        cur_raw = cell(r, "currency")
        currency = normalize_currency(cur_raw) if cur_raw else None
        if cur_raw and currency is None:
            flag("error", f"unknown currency '{cur_raw}'")
        if currency is None and cur_hint:
            currency = cur_hint
        if currency is None and not cur_raw:
            if default_currency:
                currency = default_currency
                flag("info", f"currency not given; using selected default {default_currency}")
            else:
                flag("error", "currency missing and no default selected")
        if currency and currency not in SUPPORTED_CURRENCIES:
            flag("error", f"currency {currency} is not supported (use HKD, CNY, or USD)")
        if cur_hint and currency and cur_hint != currency:
            flag("error", f"amount symbol suggests {cur_hint} but currency column says {currency}")

        text_blob = " ".join([cell(r, "counterparty"), cell(r, "description"), cell(r, "category"), cell(r, "kind")])
        kind_raw = cell(r, "kind").strip().lower()
        kind = kind_raw if kind_raw in ("operating", "refund", "financing", "transfer") else None
        kind_reason = "from file" if kind else None
        if not kind:
            kind, kind_reason = suggest_kind(text_blob)
        if not kind:
            kind, kind_reason = "operating", "default"
        if kind == "refund" and direction == "outflow":
            flag("warning", "refund marked as outflow; check whether this is a refund paid to a customer")
        if kind == "financing" and direction == "inflow":
            flag("info", "financing inflow: included in cash, excluded from operating burn")
        if kind == "transfer":
            flag("info", "transfer between company accounts: excluded from burn and income")

        # category
        cat_raw = cell(r, "category").strip()
        category = None
        cat_reason = None
        if cat_raw:
            match = [c for c in CATEGORIES if c.lower() == cat_raw.lower() or c.lower().startswith(cat_raw.lower())]
            if match:
                category, cat_reason = match[0], "from file"
            else:
                flag("warning", f"category '{cat_raw}' is not a standard category; please map it")
        cp_norm = _norm(cell(r, "counterparty"))
        hist = ctx.counterparty_history.get(cp_norm) if cp_norm else None
        if not category and kind in ("operating", "refund"):
            if hist and hist.get("category"):
                category, cat_reason = hist["category"], "same counterparty previously"
            else:
                category, cat_reason = suggest_category(text_blob)

        # program / milestone
        prog_raw = cell(r, "program").strip().lower()
        program_id = None
        prog_reason = None
        allocation = "unallocated"
        if prog_raw:
            if prog_raw in ("shared", "company", "overhead", "g&a", "all"):
                allocation, prog_reason = "shared", "marked shared in file"
            else:
                for p in ctx.programs:
                    if prog_raw in (p["code"].lower(), p["name"].lower()):
                        program_id, prog_reason, allocation = p["id"], "from file", "direct"
                if program_id is None:
                    flag("warning", f"program '{cell(r, 'program')}' not found; left unallocated")
        else:
            low = text_blob.lower()
            hits = [p for p in ctx.programs if p["code"].lower() in low]
            if len(hits) == 1:
                program_id, prog_reason, allocation = hits[0]["id"], f"program code '{hits[0]['code']}' in text", "direct"
            elif len(hits) > 1:
                flag("warning", "text mentions several programs; allocation is ambiguous")
            elif hist and hist.get("program_id"):
                program_id, prog_reason, allocation = hist["program_id"], "same counterparty previously", "direct"
        if category in ("Personnel", "Facilities", "Overhead") and allocation == "unallocated":
            allocation, prog_reason = "shared", "company-wide cost category"
        milestone_id = None
        ms_raw = cell(r, "milestone").strip().lower()
        if ms_raw and program_id:
            for m in ctx.milestones:
                if m["program_id"] == program_id and m["name"].lower() == ms_raw:
                    milestone_id = m["id"]
            if milestone_id is None:
                flag("warning", f"milestone '{cell(r, 'milestone')}' not found for that program")
        elif program_id:
            low = text_blob.lower()
            cands = [m for m in ctx.milestones if m["program_id"] == program_id and m["name"].lower() in low]
            if len(cands) == 1:
                milestone_id = cands[0]["id"]

        # account
        acc_raw = cell(r, "account").strip().lower()
        account_id = None
        legal_entity = cell(r, "legal_entity").strip() or None
        if acc_raw:
            for a in ctx.accounts:
                if a["name"].lower() == acc_raw:
                    account_id = a["id"]
                    legal_entity = legal_entity or a.get("legal_entity")
            if account_id is None:
                flag("warning", f"account '{cell(r, 'account')}' not found; transaction will not affect cash")
        elif default_account:
            account_id = int(default_account)
            acc = next((a for a in ctx.accounts if a["id"] == account_id), None)
            if acc:
                legal_entity = legal_entity or acc.get("legal_entity")
                if currency and acc["currency"] != currency:
                    flag("warning", f"currency {currency} differs from account currency {acc['currency']}")

        parsed = None
        if d and amount and direction and currency in SUPPORTED_CURRENCIES:
            minor = to_minor(amount, currency)
            h = dedupe_hash(d, minor, currency, direction, cell(r, "counterparty"), cell(r, "description"), cell(r, "reference"))
            if h in ctx.existing_hashes:
                flag("duplicate", "matches a transaction already in the ledger (likely re-import)")
            if h in seen_in_file:
                flag("duplicate", f"duplicate of row {seen_in_file[h]} in this file")
            else:
                seen_in_file[h] = sheet_row
            commitment_match = None
            if direction == "outflow":
                for c in ctx.open_commitments:
                    if c["currency"] == currency and c["amount_minor"] == minor and cp_norm and _norm(c["counterparty"]) == cp_norm:
                        commitment_match = c["id"]
                        flag("info", f"matches open commitment #{c['id']}; link it to avoid double counting")
                        break
            parsed = {
                "txn_date": d.isoformat(), "amount_minor": minor, "currency": currency, "direction": direction,
                "kind": kind, "counterparty": cell(r, "counterparty") or None, "description": cell(r, "description") or None,
                "category": category, "program_id": program_id, "milestone_id": milestone_id, "allocation": allocation,
                "legal_entity": legal_entity, "account_id": account_id, "reference": cell(r, "reference") or None,
                "dedupe_hash": h, "commitment_id": commitment_match,
            }
        suggestion = {
            "kind": {"value": kind, "reason": kind_reason},
            "category": {"value": category, "reason": cat_reason},
            "program_id": {"value": program_id, "reason": prog_reason},
            "allocation": allocation,
            "basis": "rule-based suggestion (keywords, codes, counterparty history); review before committing",
        }
        has_error = any(i["level"] == "error" for i in issues)
        is_dup = any(i["level"] == "duplicate" for i in issues)
        staged.append({
            "sheet_row": sheet_row, "raw": raw, "parsed": parsed, "issues": issues, "suggestion": suggestion,
            "decision": "skip" if (has_error or is_dup) else "include",
        })
    return staged, summarize(staged)


def summarize(staged: list[dict], statement: dict | None = None) -> dict:
    """Reconciliation summary of what would be committed."""
    total = len(staged)
    included = [s for s in staged if s["decision"] == "include" and s["parsed"]]
    errors = sum(1 for s in staged if any(i["level"] == "error" for i in s["issues"]))
    dups = sum(1 for s in staged if any(i["level"] == "duplicate" for i in s["issues"]))
    warnings = sum(1 for s in staged if any(i["level"] == "warning" for i in s["issues"]))
    by: dict[str, dict[str, int]] = {}
    unallocated: dict[str, int] = {}
    dates = []
    per_account: dict[str, int] = {}
    for s in included:
        p = s["parsed"]
        key = f"{p['currency']} {p['kind']} {p['direction']}"
        by.setdefault(key, {"count": 0, "amount_minor": 0})
        by[key]["count"] += 1
        by[key]["amount_minor"] += p["amount_minor"]
        if p["allocation"] == "unallocated" and p["kind"] in ("operating", "refund"):
            unallocated[p["currency"]] = unallocated.get(p["currency"], 0) + p["amount_minor"]
        dates.append(p["txn_date"])
        acc = str(p["account_id"])
        per_account[acc] = per_account.get(acc, 0) + (p["amount_minor"] if p["direction"] == "inflow" else -p["amount_minor"])
    result = {
        "rows_total": total,
        "rows_included": len(included),
        "rows_skipped": total - len(included),
        "rows_with_errors": errors,
        "rows_duplicate": dups,
        "rows_with_warnings": warnings,
        "date_range": [min(dates), max(dates)] if dates else None,
        "totals": [{"group": k, **v} for k, v in sorted(by.items())],
        "unallocated_minor_by_currency": unallocated,
        "net_movement_by_account_minor": per_account,
        "note": "Totals are per currency; currencies are never combined in this summary.",
    }
    if statement:
        # optional bank-statement check: opening + net movement should equal closing
        try:
            acc = str(statement["account_id"])
            expected = int(statement["closing_minor"]) - int(statement["opening_minor"])
            actual = per_account.get(acc, 0)
            result["statement_check"] = {"account_id": statement["account_id"], "expected_movement_minor": expected, "imported_movement_minor": actual, "difference_minor": actual - expected, "reconciled": actual == expected}
        except (KeyError, ValueError, TypeError):
            result["statement_check"] = {"error": "statement check needs account_id, opening_minor and closing_minor"}
    return result


def safe_csv_cell(value) -> str:
    """Protect exported CSV text from formula injection (OWASP guidance)."""
    if value is None:
        return ""
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def to_csv(header: list[str], records: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([safe_csv_cell(h) for h in header])
    for r in records:
        w.writerow([safe_csv_cell(c) for c in r])
    return buf.getvalue()
