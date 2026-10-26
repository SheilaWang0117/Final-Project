"""Planning Assistant: answers grounded in deterministic tools and stored sources.

Post-checks after the model answers:
- every money/percentage figure in the answer must appear in a tool result,
  otherwise it is listed as an unverified figure;
- every source URL must come from a tool result, otherwise it is removed.
In demo mode a deterministic template answers common questions with the same
tools and no model call (clearly labeled).
"""

from __future__ import annotations

import json
import re

from .common import Deps, make_agent, mode
from .runner import Recorder, finish_ok, record_demo_run, run_agent
from .schemas import AssistantAnswer
from .tools import ASSISTANT_TOOLS

_FIG_RE = re.compile(r"(?:USD|HKD|CNY)\s?-?[\d,]+(?:\.\d+)?|-?\d+(?:\.\d+)?%|\b\d{4}-\d{2}\b")


def _tool_outputs(rec: Recorder, deps: Deps) -> str:
    return json.dumps(deps.extra.get("tool_results", []), default=str)


def ground_check(answer: AssistantAnswer, tool_text: str, allowed_urls: set[str]) -> dict:
    text = answer.answer + " " + " ".join(f.value for f in answer.key_figures)
    figures = set(_FIG_RE.findall(text))
    unverified = sorted(f for f in figures if f.replace(" ", "") not in tool_text.replace(" ", ""))
    kept_sources = [s for s in answer.sources if s.url in allowed_urls]
    removed = [s.url for s in answer.sources if s.url not in allowed_urls]
    return {"unverified_figures": unverified, "removed_sources": removed, "kept_sources": [s.model_dump() for s in kept_sources]}


def _capture_tools():
    """Wrap tools so their outputs are kept for grounding checks."""
    import functools

    wrapped = []
    for t in ASSISTANT_TOOLS:
        @functools.wraps(t)
        async def w(ctx, *a, __t=t, **k):
            res = await __t(ctx, *a, **k)
            ctx.deps.extra.setdefault("tool_results", []).append(res)
            return res
        wrapped.append(w)
    return wrapped


async def ask(question: str, *, program_id: int | None = None, model=None, language: str = "en") -> dict:
    rec = Recorder("planning_assistant", mode() if model is None else "test")
    deps = Deps(rec=rec, program_id=program_id, tool_caps={"get_competitor_events": 3, "get_regulatory_documents": 3, "simulate_milestone_delay": 4})
    if rec.mode == "demo":
        from .demo_answers import template_answer

        out = await template_answer(question, deps, language=language)
        run = record_demo_run("planning_assistant", rec, "Template answer from deterministic tools; no model call.")
        return {**out, "method": "template_demo", "run": run}
    agent = make_agent("assistant", AssistantAnswer, model=model, tools=_capture_tools())
    prompt = f"Question from the team: {question}"
    if program_id:
        prompt += f"\n(The user is viewing program id {program_id}.)"
    if language == "zh":
        prompt += ("\nWrite `answer`, key-figure labels, assumptions, gaps and suggested actions in Simplified Chinese. "
                   "Copy every figure value exactly as the tool returned it (for example 'USD 1,234.00'); do not convert or reformat numbers.")
    output = await run_agent(agent, prompt, deps=deps, rec=rec)
    tool_text = _tool_outputs(rec, deps)
    allowed = {s["url"] for s in rec.sources}
    check = ground_check(output, tool_text, allowed)
    rec.step("grounding_check", {"unverified_figures": check["unverified_figures"], "removed_sources": check["removed_sources"]}, ok=not check["unverified_figures"])
    run = finish_ok(rec)
    data = output.model_dump()
    data["sources"] = check["kept_sources"] or [s for s in rec.sources if s["url"]][:6]
    return {**data, "grounding": check, "method": "llm", "run": run}
