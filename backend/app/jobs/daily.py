"""Daily research job (run by cron/launchd or by hand).

    cd backend && ../.venv/bin/python -m app.jobs.daily

Builds today's briefing, then refreshes competitor intelligence and regulatory
documents for every confirmed, active program, within the configured per-run
and daily limits. Each step is recorded as a job, and a failed step does not
stop the next one. A computer that is asleep or shut down does not run this
job; the app then shows the last briefing with a stale label.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from ..agents.intelligence import build_briefing, refresh_competitors  # noqa: E402
from ..agents.regulatory import refresh_regulatory  # noqa: E402
from ..config import get_settings  # noqa: E402
from ..db import connect, init_db  # noqa: E402
from . import manager  # noqa: E402


async def main_async(skip_regulatory: bool, max_programs: int) -> dict:
    s = get_settings()
    init_db()
    summary = {"mode": s.app_mode, "steps": []}
    if s.is_demo:
        summary["note"] = "Demo mode: fixtures only."
    jid = manager.create_job("daily_briefing", {"trigger": "daily CLI"})
    summary["steps"].append({"briefing": await manager.run_job(abs(jid), build_briefing)})
    conn = connect()
    try:
        progs = [r["id"] for r in conn.execute("SELECT id FROM programs WHERE archived = 0 AND status = 'active' AND profile_confirmed_at IS NOT NULL ORDER BY priority LIMIT ?", (max_programs,))]
    finally:
        conn.close()
    for pid in progs:
        jid = manager.create_job("competitor_refresh", {"program_id": pid, "trigger": "daily CLI"})
        summary["steps"].append({f"competitors:{pid}": await manager.run_job(abs(jid), refresh_competitors, program_id=pid)})
        if not skip_regulatory:
            jid = manager.create_job("regulatory_refresh", {"program_id": pid, "trigger": "daily CLI"})
            summary["steps"].append({f"regulatory:{pid}": await manager.run_job(abs(jid), refresh_regulatory, program_id=pid)})
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the daily research job once.")
    ap.add_argument("--skip-regulatory", action="store_true", help="only briefing and competitor refresh")
    ap.add_argument("--max-programs", type=int, default=5)
    args = ap.parse_args()
    out = asyncio.run(main_async(args.skip_regulatory, args.max_programs))
    print(json.dumps(out, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
