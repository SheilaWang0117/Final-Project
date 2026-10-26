"""Agent construction helpers shared by all roles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from ..config import get_settings
from .llm import build_model
from .runner import Recorder

PROMPTS = Path(__file__).resolve().parent / "prompts"


def instructions(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8") + "\n\n" + (PROMPTS / "_safety.md").read_text(encoding="utf-8")


@dataclass
class Deps:
    rec: Recorder
    program_id: int | None = None
    candidates: dict[str, dict] = field(default_factory=dict)  # id -> item the agent may read
    tool_caps: dict[str, int] = field(default_factory=dict)
    read_texts: dict[str, str] = field(default_factory=dict)  # id -> text the agent actually read
    extra: dict[str, Any] = field(default_factory=dict)


def make_agent(name: str, output_type, *, model=None, tools=(), retries: int = 2) -> Agent:
    return Agent(
        model if model is not None else build_model(),
        output_type=output_type,
        instructions=instructions(name),
        deps_type=Deps,
        tools=list(tools),
        retries=retries,
        name=name,
    )


def mode() -> str:
    return "demo" if get_settings().is_demo else "live"


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def is_verbatim(quote: str, source: str, min_len: int = 3) -> bool:
    q = normalize_ws(quote).strip(" .\"'“”")
    return len(q) >= min_len and q in normalize_ws(source)
