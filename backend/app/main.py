"""FastAPI application entry point.

Run (from backend/):  ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
The server is meant for local use and binds to 127.0.0.1. If frontend/dist
exists, the built React app is served from the same origin.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from .api import finance, imports, intel, pipelines, system  # noqa: E402
from .config import REPO_ROOT, get_settings, redact  # noqa: E402
from .db import connect, get_setting, init_db  # noqa: E402
from .jobs import manager  # noqa: E402
from .research.registry import seed as seed_registry  # noqa: E402


async def _scheduler_loop():
    """While the app runs, build today's briefing once after BRIEFING_HOUR local time."""
    from .agents.intelligence import build_briefing, briefing_date

    s = get_settings()
    while True:
        try:
            conn = connect()
            try:
                day, tz = briefing_date(conn)
                have = conn.execute("SELECT 1 FROM briefings WHERE briefing_date = ? AND status IN ('fresh','partial')", (day,)).fetchone()
            finally:
                conn.close()
            hour = datetime.now(ZoneInfo(tz)).hour
            if not have and hour >= s.briefing_hour:
                manager.start("daily_briefing", build_briefing, {"trigger": "in-app scheduler"})
        except Exception as exc:  # noqa: BLE001
            print("scheduler:", redact(str(exc)))
        await asyncio.sleep(900)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    init_db()
    conn = connect()
    try:
        seed_registry(conn)
        conn.commit()
        empty = not conn.execute("SELECT 1 FROM programs LIMIT 1").fetchone()
    finally:
        conn.close()
    if s.is_demo and empty:
        from .demo.seed import seed_all

        conn = connect()
        try:
            seed_all(conn)
        finally:
            conn.close()
    manager.mark_orphans()
    task = asyncio.create_task(_scheduler_loop()) if (s.enable_scheduler and not s.is_demo and s.llm_ready) else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Ocra Pipeline Tracker", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": redact(f"Unexpected error: {type(exc).__name__}")})


for r in (pipelines.router, finance.router, imports.router, intel.router, system.router):
    app.include_router(r)

DIST = REPO_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")


__all__ = ["app", "get_setting"]
