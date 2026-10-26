"""Currency conversion with explicit, recorded rates.

Lookup order for converting `src` -> `dst` on a date:
1. Same currency: no conversion.
2. A direct (src, dst) rate dated on or before the date (latest wins).
3. An inverse (dst, src) rate on or before the date (1 / rate).
4. A cross rate through EUR when both legs exist for the same rate date
   (this is how ECB reference rates are published).
If none exists, the amount is NOT converted and the caller must report it as
missing. Rates older than `stale_days` are used but flagged.
Manual rates win over other sources on the same date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import ROUNDING, exponent, from_minor, to_minor

RATE_PRECISION = Decimal("0.0000000001")


@dataclass(frozen=True)
class Rate:
    base: str
    quote: str
    rate: Decimal  # 1 base = rate quote
    rate_date: date
    source: str
    method: str = "manual"


@dataclass(frozen=True)
class Conversion:
    amount_minor: int
    currency: str
    rate: Decimal
    rate_date: date | None
    source: str
    method: str  # identity | direct | inverse | cross_eur
    stale: bool = False


class MissingRate(LookupError):
    pass


class FxTable:
    def __init__(self, rates: list[Rate], stale_days: int = 10):
        self.stale_days = stale_days
        self._by_pair: dict[tuple[str, str], list[Rate]] = {}
        for r in rates:
            self._by_pair.setdefault((r.base, r.quote), []).append(r)
        for lst in self._by_pair.values():
            # newest first; manual beats others on the same date
            lst.sort(key=lambda r: (r.rate_date, r.method == "manual"), reverse=True)

    def _latest(self, base: str, quote: str, on: date) -> Rate | None:
        for r in self._by_pair.get((base, quote), []):
            if r.rate_date <= on:
                return r
        return None

    def rate(self, src: str, dst: str, on: date) -> tuple[Decimal, date | None, str, str]:
        if src == dst:
            return Decimal(1), None, "identity", "identity"
        direct = self._latest(src, dst, on)
        inverse = self._latest(dst, src, on)
        best = None
        if direct and (not inverse or direct.rate_date >= inverse.rate_date):
            best = (direct.rate, direct.rate_date, direct.source, "direct")
        elif inverse:
            best = ((Decimal(1) / inverse.rate).quantize(RATE_PRECISION), inverse.rate_date, inverse.source, "inverse")
        cross = self._cross_eur(src, dst, on)
        if cross and (best is None or (best[1] and cross[1] and cross[1] > best[1])):
            best = cross
        if best is None:
            raise MissingRate(f"No {src}->{dst} rate on or before {on.isoformat()}")
        return best

    def _cross_eur(self, src: str, dst: str, on: date):
        def eur_to(cur: str) -> Rate | None:
            if cur == "EUR":
                return Rate("EUR", "EUR", Decimal(1), on, "identity", "identity")
            return self._latest("EUR", cur, on)

        a, b = eur_to(src), eur_to(dst)
        if not a or not b:
            return None
        if a.source != "identity" and b.source != "identity" and a.rate_date != b.rate_date:
            return None
        rate_date = a.rate_date if a.source != "identity" else b.rate_date
        rate = (b.rate / a.rate).quantize(RATE_PRECISION)
        source = a.source if a.source != "identity" else b.source
        return rate, rate_date, source, "cross_eur"

    def convert(self, amount_minor: int, src: str, dst: str, on: date) -> Conversion:
        rate, rate_date, source, method = self.rate(src, dst, on)
        if method == "identity":
            return Conversion(amount_minor, dst, rate, None, "identity", "identity")
        value = from_minor(amount_minor, src) * rate
        converted = to_minor(value, dst)
        stale = bool(rate_date and (on - rate_date).days > self.stale_days)
        return Conversion(converted, dst, rate, rate_date, source, method, stale)


def describe_method() -> str:
    return (
        "Each amount is converted individually at the most recent recorded rate dated on or before "
        "the transaction (or forecast as-of) date; manual rates take precedence on the same date; "
        "ECB reference rates are crossed through EUR. Results are rounded half-up to the reporting "
        f"currency's minor unit (e.g. {exponent('USD')} decimals for USD). Amounts with no available "
        "rate are excluded from totals and listed as missing, never combined unconverted."
    )


__all__ = ["Rate", "Conversion", "FxTable", "MissingRate", "describe_method", "ROUNDING"]
