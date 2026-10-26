"""Money helpers: integer minor units, Decimal parsing, explicit rounding.

Rounding rule: ROUND_HALF_UP to the currency's minor unit, applied once at the
end of each conversion or allocation step. No floats are used for money.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_EXPONENT = {"USD": 2, "HKD": 2, "CNY": 2, "EUR": 2}
SUPPORTED_CURRENCIES = ("USD", "HKD", "CNY")
CURRENCY_ALIASES = {
    "RMB": "CNY",
    "CNH": "CNY",
    "人民币": "CNY",
    "元": "CNY",
    "港币": "HKD",
    "港元": "HKD",
    "美元": "USD",
    "US$": "USD",
    "HK$": "HKD",
    "¥": "CNY",
    "￥": "CNY",
}
ROUNDING = ROUND_HALF_UP


class MoneyError(ValueError):
    pass


def normalize_currency(value: str | None) -> str | None:
    """Return an ISO code, or None if unknown/ambiguous ("$" is ambiguous)."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in CURRENCY_EXPONENT:
        return text
    return CURRENCY_ALIASES.get(text) or CURRENCY_ALIASES.get(str(value).strip())


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENT[currency]
    except KeyError as exc:
        raise MoneyError(f"Unsupported currency {currency!r}") from exc


def to_minor(amount: Decimal, currency: str) -> int:
    q = Decimal(1).scaleb(-exponent(currency))
    return int((amount.quantize(q, rounding=ROUNDING)).scaleb(exponent(currency)))


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(minor).scaleb(-exponent(currency))


def fmt(minor: int | None, currency: str) -> str:
    if minor is None:
        return "n/a"
    value = from_minor(minor, currency)
    return f"{currency} {value:,.2f}"


@dataclass(frozen=True)
class ParsedAmount:
    value: Decimal | None
    currency_hint: str | None
    issues: tuple[str, ...]


_SYMBOL_RE = re.compile(r"(US\$|HK\$|RMB|CNY|HKD|USD|CNH|[$¥￥])", re.IGNORECASE)


def parse_amount(raw: object) -> ParsedAmount:
    """Parse a spreadsheet amount without guessing silently.

    Handles thousands separators, parentheses negatives, trailing minus,
    and currency symbols. A lone "$" is reported as ambiguous (USD or HKD).
    """
    issues: list[str] = []
    if raw is None:
        return ParsedAmount(None, None, ("missing amount",))
    if isinstance(raw, (int, Decimal)):
        return ParsedAmount(Decimal(raw), None, ())
    if isinstance(raw, float):
        # openpyxl returns floats for numeric cells; repr() keeps the shortest exact form.
        return ParsedAmount(Decimal(repr(raw)), None, ())
    text = str(raw).strip()
    if not text:
        return ParsedAmount(None, None, ("missing amount",))
    hint = None
    m = _SYMBOL_RE.search(text)
    if m:
        sym = m.group(1).upper()
        if sym == "$":
            issues.append("'$' symbol is ambiguous (USD or HKD); confirm currency")
        else:
            hint = normalize_currency(sym)
        text = _SYMBOL_RE.sub("", text)
    text = text.replace(" ", "").replace(" ", "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-"):
        negative, text = (not negative), text[1:]
    if text.startswith("+"):
        text = text[1:]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            issues.append("decimal comma format detected; confirm amount")
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if len(tail) == 3 and re.fullmatch(r"\d{1,3}(,\d{3})*", text):
            text = text.replace(",", "")
        else:
            issues.append("comma may be a decimal separator; confirm amount")
            return ParsedAmount(None, hint, tuple(issues))
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return ParsedAmount(None, hint, tuple(issues + [f"not a number: {raw!s:.40}"]))
    try:
        value = Decimal(text)
    except InvalidOperation:
        return ParsedAmount(None, hint, tuple(issues + ["not a number"]))
    return ParsedAmount(-value if negative else value, hint, tuple(issues))


def allocate(minor: int, weights_bps: dict[str, int]) -> dict[str, int]:
    """Split an amount by basis-point weights; remainders go to the largest weights.

    Weights must sum to 10000. The parts always sum exactly to `minor`.
    """
    total = sum(weights_bps.values())
    if total != 10000:
        raise MoneyError(f"allocation weights must sum to 10000 bps, got {total}")
    raw = {k: Decimal(minor) * w / 10000 for k, w in weights_bps.items()}
    parts = {k: int(v.to_integral_value(rounding="ROUND_FLOOR")) for k, v in raw.items()}
    remainder = minor - sum(parts.values())
    order = sorted(weights_bps, key=lambda k: (-(raw[k] - parts[k]), -weights_bps[k], k))
    for k in order[:remainder]:
        parts[k] += 1
    return parts
