"""ECB euro foreign exchange reference rates (official, free, daily)."""

from __future__ import annotations

from defusedxml import ElementTree as ET

from ..cache import cached_fetch

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


async def fetch_reference_rates() -> dict:
    res = await cached_fetch(ECB_URL, ttl_hours=6, max_bytes=200_000)
    root = ET.fromstring(res.body)
    rates, day = {}, None
    for el in root.iter():
        if el.tag.endswith("Cube") and el.get("time"):
            day = el.get("time")
        if el.tag.endswith("Cube") and el.get("currency"):
            rates[el.get("currency")] = el.get("rate")
    if not day or not rates:
        raise ValueError("ECB response did not contain rates")
    return {"date": day, "rates": rates, "url": ECB_URL, "retrieved_at": res.retrieved_at}
