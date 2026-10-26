"""Instrumented, bounded agent execution.

Each run records: provider, model, mode, duration, requests, input tokens,
cached-input tokens (as reported by the provider), output and reasoning
tokens, tool calls with timings, application cache hits/misses, sources,
errors, and an estimated cost from the dated pricing table (or unknown).
No prompts, hidden reasoning, or secrets are stored in traces.
"""

from __future__ import annotations

import asyncio
import functools
import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded

from ..config import contains_secret, get_settings, redact
from ..db import connect, jdump, utc_now
from ..research.cache import CacheStats
from .llm import GATEWAY_CACHE, ProviderNotReady, estimate_cost


class AgentFailure(RuntimeError):
    """A run that ended without a validated result. Message is safe to show."""


class DailyLimitReached(AgentFailure):
    pass


@dataclass
class Recorder:
    agent: str
    mode: str
    job_id: int | None = None
    run_id: int | None = None
    started: float = field(default_factory=time.monotonic)
    trace: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    cache: CacheStats = field(default_factory=CacheStats)
    tool_counts: dict[str, int] = field(default_factory=dict)
    blocked: list[dict] = field(default_factory=list)
    gateway: list[str] = field(default_factory=list)
    quarantined: int = 0

    def start(self, conn: sqlite3.Connection) -> "Recorder":
        if self.run_id is not None:
            return self
        s = get_settings()
        self.run_id = conn.execute(
            "INSERT INTO agent_runs (agent, job_id, mode, provider, model, started_at, status, prompt_version) VALUES (?,?,?,?,?,?, 'running', ?)",
            (self.agent, self.job_id, self.mode, s.llm_provider if self.mode == "live" else "none",
             s.model_name if self.mode == "live" else None, utc_now(), PROMPT_VERSION),
        ).lastrowid
        conn.commit()
        return self

    def step(self, name: str, detail: dict | None = None, ok: bool = True, ms: int = 0, error: str | None = None):
        self.trace.append({"step": name, "ok": ok, "ms": ms, "detail": _safe(detail or {}), "error": redact(error) if error else None,
                           "at": datetime.now(timezone.utc).strftime("%H:%M:%S")})

    def source(self, title: str, url: str, retrieved_at: str | None, from_cache: bool | None = None):
        if not any(s["url"] == url for s in self.sources):
            self.sources.append({"title": title[:200], "url": url, "retrieved_at": retrieved_at, "from_cache": from_cache})

    def finish(self, conn: sqlite3.Connection, *, usage=None, status: str = "succeeded", error: str | None = None) -> dict:
        s = get_settings()
        duration = int((time.monotonic() - self.started) * 1000)
        inp = out = cached = reasoning = requests = tools = None
        if usage is not None:
            inp, out = usage.input_tokens, usage.output_tokens
            cached = usage.cache_read_tokens
            reasoning = (usage.details or {}).get("reasoning_tokens")
            requests, tools = usage.requests, usage.tool_calls
        cost = version = None
        if self.mode == "live" and inp is not None:
            cost, version = estimate_cost(s.model_name, inp or 0, cached or 0, out or 0)
            hits = self.gateway.count("HIT")
            if self.gateway and hits == len(self.gateway):
                cost = "0"
                version = f"{version}; all requests were gateway cache hits (assumed not billed by the model provider; billing not verified)"
            elif hits:
                version = f"{version}; {hits}/{len(self.gateway)} gateway cache hits - estimate is an upper bound"
        conn.execute(
            "UPDATE agent_runs SET duration_ms=?, status=?, requests=?, input_tokens=?, cached_input_tokens=?, output_tokens=?, reasoning_tokens=?, tool_calls=?, "
            "app_cache_hits=?, app_cache_misses=?, cost_usd=?, pricing_version=?, trace_json=?, sources_json=?, error=?, gateway_cache_hits=?, gateway_cache_misses=?, quarantined_items=? WHERE id=?",
            (duration, status, requests, inp, cached, out, reasoning, tools, self.cache.hits, self.cache.misses, cost, version,
             jdump(self.trace + ([{"step": "blocked_actions", "ok": False, "detail": {"items": self.blocked}}] if self.blocked else [])),
             jdump(self.sources[:60]), redact(error)[:1000] if error else None,
             self.gateway.count("HIT") if self.gateway else None, (len(self.gateway) - self.gateway.count("HIT")) if self.gateway else None, self.quarantined, self.run_id),
        )
        conn.commit()
        return run_summary(conn, self.run_id)


PROMPT_VERSION = "2026-10-24.1"


def _safe(d: Any, depth: int = 0) -> Any:
    """Redact and truncate trace details."""
    if depth > 3:
        return "…"
    if isinstance(d, dict):
        return {str(k)[:40]: _safe(v, depth + 1) for k, v in list(d.items())[:15]}
    if isinstance(d, (list, tuple)):
        return [_safe(v, depth + 1) for v in list(d)[:10]]
    if isinstance(d, str):
        return redact(d)[:300]
    return d


def run_summary(conn, run_id: int) -> dict:
    r = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    d = dict(r)
    d["trace"] = json.loads(d.pop("trace_json") or "[]")
    d["sources"] = json.loads(d.pop("sources_json") or "[]")
    return d


def check_daily_budget(conn: sqlite3.Connection) -> None:
    s = get_settings()
    day = datetime.now(timezone.utc).date().isoformat()
    r = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(COALESCE(input_tokens,0) + COALESCE(output_tokens,0)),0) AS tok, COALESCE(SUM(CAST(cost_usd AS REAL)),0) AS cost "
        "FROM agent_runs WHERE mode = 'live' AND started_at >= ?", (day,)).fetchone()
    if r["n"] >= s.daily_run_limit:
        raise DailyLimitReached(f"Daily live-run limit reached ({s.daily_run_limit}). Raise DAILY_RUN_LIMIT or wait until tomorrow (UTC).")
    if r["tok"] >= s.daily_token_limit:
        raise DailyLimitReached(f"Daily token limit reached ({s.daily_token_limit:,}).")
    if r["cost"] >= s.daily_cost_limit_usd:
        raise DailyLimitReached(f"Daily estimated cost limit reached (${s.daily_cost_limit_usd}).")


def usage_limits(request_limit: int | None = None, tool_calls_limit: int | None = None, total_tokens: int | None = None) -> UsageLimits:
    s = get_settings()
    return UsageLimits(
        request_limit=request_limit or s.run_request_limit,
        tool_calls_limit=tool_calls_limit if tool_calls_limit is not None else s.run_tool_calls_limit,
        total_tokens_limit=total_tokens or s.run_total_tokens_limit,
    )


async def run_agent(agent, prompt: str, *, deps, rec: Recorder, limits: UsageLimits | None = None, timeout: float | None = None):
    """Run a PydanticAI agent with limits and a timeout, recording the outcome.

    Returns the validated output. Raises AgentFailure with a safe message.
    """
    s = get_settings()
    conn = connect()
    try:
        rec.start(conn)
        try:
            check_daily_budget(conn)
        except DailyLimitReached as exc:
            rec.finish(conn, status="refused", error=str(exc))
            raise
        t0 = time.monotonic()
        gw_token = GATEWAY_CACHE.set(rec.gateway)
        try:
            result = await asyncio.wait_for(agent.run(prompt, deps=deps, usage_limits=limits or usage_limits()), timeout=timeout or s.run_timeout_seconds)
        except UsageLimitExceeded as exc:
            rec.step("model_run", ok=False, ms=int((time.monotonic() - t0) * 1000), error=f"usage limit: {exc}")
            rec.finish(conn, status="limit_exceeded", error=f"Stopped by a usage limit: {exc}")
            raise AgentFailure(f"The agent stopped at a safety limit ({exc}). No partial result was saved.") from exc
        except UnexpectedModelBehavior as exc:
            rec.step("model_run", ok=False, ms=int((time.monotonic() - t0) * 1000), error=f"invalid output: {exc}")
            rec.finish(conn, status="invalid_output", error=f"Model output failed validation: {exc}")
            raise AgentFailure("The model returned output that failed validation after retries. Nothing was saved.") from exc
        except asyncio.TimeoutError as exc:
            rec.finish(conn, status="timeout", error="run timed out")
            raise AgentFailure("The agent run timed out. Nothing was saved.") from exc
        except ProviderNotReady as exc:
            rec.finish(conn, status="not_configured", error=str(exc))
            raise AgentFailure(str(exc)) from exc
        except ModelHTTPError as exc:
            msg = redact(f"provider error {exc.status_code}: {str(exc.body)[:200]}")
            filtered = "content management policy" in str(exc.body) or "content_filter" in str(exc.body)
            rec.finish(conn, status="content_filtered" if filtered else "provider_error", error=msg)
            if filtered:
                raise AgentFailure("The provider's content filter rejected the request (often caused by instruction-like text in retrieved content). Nothing was saved.") from exc
            raise AgentFailure(f"The model provider returned an error ({exc.status_code}). Nothing was saved.") from exc
        except AgentFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            rec.finish(conn, status="failed", error=f"{type(exc).__name__}: {exc}")
            raise AgentFailure(f"Agent run failed: {type(exc).__name__}") from exc
        finally:
            GATEWAY_CACHE.reset(gw_token)
        rec.step("model_run", {"requests": result.usage.requests, "tool_calls": result.usage.tool_calls}, ms=int((time.monotonic() - t0) * 1000))
        output_text = result.output.model_dump_json() if hasattr(result.output, "model_dump_json") else str(result.output)
        if contains_secret(output_text):
            # Defense in depth: a configured secret must never leave through an agent's output.
            rec.step("output_secret_check", ok=False, error="output contained a configured secret; discarded")
            rec._usage = result.usage  # type: ignore[attr-defined]
            rec.finish(conn, usage=result.usage, status="blocked_secret", error="Output contained a configured secret and was discarded.")
            raise AgentFailure("The agent output was discarded by the secret filter. Nothing was saved.")
        rec.step("output_secret_check", {"result": "clean"})
        rec._usage = result.usage  # type: ignore[attr-defined]
        return result.output
    finally:
        conn.close()


def finish_ok(rec: Recorder, status: str = "succeeded", error: str | None = None) -> dict:
    conn = connect()
    try:
        return rec.finish(conn, usage=getattr(rec, "_usage", None), status=status, error=error)
    finally:
        conn.close()


def record_demo_run(agent: str, rec: Recorder, note: str) -> dict:
    """Demo-mode runs are recorded with mode='demo' and no tokens (never simulated)."""
    conn = connect()
    try:
        if rec.run_id is None:
            rec.start(conn)
        rec.step("demo_mode", {"note": note})
        return rec.finish(conn, status="succeeded")
    finally:
        conn.close()


def traced(fn: Callable) -> Callable:
    """Decorator for agent tools: times the call, enforces per-tool caps, records the trace."""

    @functools.wraps(fn)
    async def wrapper(ctx, *args, **kwargs):
        rec: Recorder = ctx.deps.rec
        name = fn.__name__
        rec.tool_counts[name] = rec.tool_counts.get(name, 0) + 1
        cap = getattr(ctx.deps, "tool_caps", {}).get(name)
        if cap is not None and rec.tool_counts[name] > cap:
            rec.step(f"tool:{name}", {"args": kwargs or list(args)}, ok=False, error="per-tool call cap reached")
            return {"error": f"Tool call limit reached for {name} ({cap} per run). Answer with the information already gathered."}
        t0 = time.monotonic()
        try:
            res = fn(ctx, *args, **kwargs)
            if asyncio.iscoroutine(res):
                res = await res
            size = len(json.dumps(res, default=str)) if res is not None else 0
            ok = not (isinstance(res, dict) and "error" in res)
            rec.step(f"tool:{name}", {"args": kwargs or list(args), "result_chars": size}, ok=ok, ms=int((time.monotonic() - t0) * 1000),
                     error=res.get("error") if isinstance(res, dict) and not ok else None)
            return res
        except Exception as exc:  # noqa: BLE001 - tools report errors to the model as data
            rec.step(f"tool:{name}", {"args": kwargs or list(args)}, ok=False, ms=int((time.monotonic() - t0) * 1000), error=f"{type(exc).__name__}: {exc}")
            return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    return wrapper


def untrusted_block(label: str, text: str) -> str:
    """Wrap retrieved content so the model treats it as data, not instructions."""
    safe = (text or "").replace("<untrusted", "‹untrusted").replace("</untrusted", "‹/untrusted")
    return f'<untrusted_content source="{label}">\n{safe}\n</untrusted_content>'
