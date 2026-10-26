"""Persistent background jobs with status, errors, and cancellation.

Jobs run inside the API process (asyncio tasks) or from the daily CLI. Status
lives in the `jobs` table so it survives page reloads. Cancellation sets a
flag and cancels the task; work already saved stays saved and is labeled.
"""

from __future__ import annotations

import asyncio
import traceback
from typing import Awaitable, Callable

from ..config import redact
from ..db import connect, jdump, jload, utc_now

_tasks: dict[int, asyncio.Task] = {}


def create_job(kind: str, params: dict | None = None) -> int:
    conn = connect()
    try:
        running = conn.execute("SELECT id FROM jobs WHERE kind = ? AND params_json = ? AND status IN ('queued','running')", (kind, jdump(params or {}))).fetchone()
        if running:
            return -running[0]  # negative id: an identical job is already running
        jid = conn.execute("INSERT INTO jobs (kind, params_json, created_at) VALUES (?,?,?)", (kind, jdump(params or {}), utc_now())).lastrowid
        conn.commit()
        return jid
    finally:
        conn.close()


def _update(jid: int, **fields) -> None:
    conn = connect()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), jid))
        conn.commit()
    finally:
        conn.close()


async def run_job(jid: int, fn: Callable[..., Awaitable[dict]], **kwargs) -> dict:
    _update(jid, status="running", started_at=utc_now(), progress="started")
    try:
        result = await fn(job_id=jid, **kwargs)
        cov = result.get("coverage") or {}
        partial = any(not v.get("ok", True) for v in cov.values()) if isinstance(cov, dict) else False
        _update(jid, status="partial" if partial else "succeeded", finished_at=utc_now(), result_json=jdump(_slim(result)), progress="done")
        return result
    except asyncio.CancelledError:
        _update(jid, status="cancelled", finished_at=utc_now(), progress="cancelled by user")
        raise
    except Exception as exc:  # noqa: BLE001 - recorded for the UI
        _update(jid, status="failed", finished_at=utc_now(), error=redact(f"{type(exc).__name__}: {exc}")[:800], progress="failed")
        traceback.print_exc()
        return {"error": str(exc)}


def _slim(result: dict) -> dict:
    out = dict(result)
    if "run" in out and isinstance(out["run"], dict):
        r = out["run"]
        out["run"] = {k: r.get(k) for k in ("id", "agent", "status", "duration_ms", "input_tokens", "output_tokens", "cached_input_tokens", "tool_calls", "cost_usd", "app_cache_hits", "app_cache_misses", "error")}
    return out


def start(kind: str, fn, params: dict, **kwargs) -> dict:
    jid = create_job(kind, params)
    if jid < 0:
        return {"job_id": -jid, "status": "already_running"}
    _tasks[jid] = asyncio.get_running_loop().create_task(run_job(jid, fn, **kwargs))
    _tasks[jid].add_done_callback(lambda _t, j=jid: _tasks.pop(j, None))
    return {"job_id": jid, "status": "queued"}


def cancel(jid: int) -> bool:
    _update(jid, cancel_requested=1)
    t = _tasks.get(jid)
    if t and not t.done():
        t.cancel()
        return True
    conn = connect()
    try:
        n = conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status IN ('queued','running')", (utc_now(), jid)).rowcount
        conn.commit()
        return bool(n)
    finally:
        conn.close()


def get(jid: int) -> dict | None:
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["params"] = jload(d.pop("params_json"), {})
        d["result"] = jload(d.pop("result_json"), {})
        return d
    finally:
        conn.close()


def mark_orphans() -> None:
    """On startup, jobs left 'running' by a stopped process are marked failed."""
    conn = connect()
    try:
        conn.execute("UPDATE jobs SET status = 'failed', error = 'Interrupted: the app stopped while this job was running', finished_at = ? WHERE status IN ('queued','running')", (utc_now(),))
        conn.execute("UPDATE agent_runs SET status = 'interrupted' WHERE status = 'running'")
        conn.commit()
    finally:
        conn.close()
