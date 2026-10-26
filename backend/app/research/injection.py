"""Heuristic detection of instruction-like text in retrieved content.

This is one layer among several (untrusted-content framing, no write tools,
candidate-only fetching, output secret filter). It quarantines retrieved items
that look like instructions to an AI system, so they never reach the model
(which also avoids provider content-filter failures that could block a whole
research run). It will miss cleverly disguised text; the other layers remain.
"""

from __future__ import annotations

import re

PATTERNS = [
    r"ignore (all |any )?(the )?(prior|previous|above|earlier) (instructions|prompts|messages)",
    r"disregard (all |any )?(the )?(prior|previous|above|system)",
    r"\b(reveal|print|show|output|leak|include)\b.{0,40}\b(api[ _-]?key|system prompt|secret|password|environment variables|credentials)\b",
    r"\bsystem (override|prompt)\b",
    r"\byou are now\b",
    r"\b(admin|developer|god) mode\b",
    r"\bupload\b.{0,40}\b(budget|financ|database|records)\b",
    r"\bnew instructions?\b.{0,20}\b(from|for) the (operator|developer|system)\b",
    r"</?\s*untrusted_content",
    r"PORTKEY_API_KEY|OPENAI_API_KEY",
    r"忽略.{0,10}(指令|指示)",
    r"(输出|泄露|显示).{0,10}(密钥|API)",
]
_RX = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.IGNORECASE)


def instruction_like(text: str) -> str | None:
    m = _RX.search(text or "")
    return m.group(0)[:80] if m else None


def scrub(text: str) -> tuple[str, int]:
    """Replace instruction-like lines in long documents; return (text, lines_removed)."""
    out, removed = [], 0
    for line in (text or "").splitlines():
        if instruction_like(line):
            out.append("[line removed by the app: instruction-like text in retrieved content]")
            removed += 1
        else:
            out.append(line)
    return "\n".join(out), removed


def quarantine(items: dict[str, dict], rec) -> dict[str, dict]:
    """Drop candidates whose title/excerpt look like instructions; record them in the trace."""
    kept = {}
    for k, it in items.items():
        hit = instruction_like(f"{it.get('title', '')} {it.get('excerpt', '')}")
        if hit:
            rec.quarantined += 1
            rec.step("quarantine", {"item": it.get("url", "")[:120], "matched": hit}, ok=False, error="instruction-like retrieved text withheld from the model")
        else:
            kept[k] = it
    return kept
