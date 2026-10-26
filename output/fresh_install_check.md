# Fresh-install check (rerun 2026-10-26, after the phase map, theme and font changes)

Method: copied exactly the files git would include (`git ls-files --others --exclude-standard`, so `.env`, databases, `node_modules`, `.venv`, and `frontend/dist` were excluded) into an empty folder `fresh/repo`, and wrote a `.env` one directory above it (`fresh/.env`) containing only a **dummy** key and `APP_MODE=demo`. The real shell variables `PORTKEY_API_KEY` and `OPENAI_API_KEY` were unset for every command, so the real key could not be used.

| Step | Result |
|---|---|
| `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt` | OK (Python 3.14.7) |
| `cd frontend && npm ci && npm run build` | OK (bundled fonts: Fredoka, Space Grotesk, JetBrains Mono) |
| Install time (warm pip/npm caches on this Mac) | 15 seconds; expect a few minutes on a clean machine |
| Start server (`uvicorn app.main:app --port 8011`) | OK; frontend served (HTTP 200) |
| `/api/status` | mode `demo`, provider `portkey`, model `gpt-6-luna`, key present, **key origin `parent .env`**, live calls off (demo) |
| Synthetic demo data seeded on first start | yes; `/api/phase-map` returns the three hypothetical pipelines with gates in order |
| Dummy key appears in server log | no (0 matches) |
| `pip install -r backend/requirements-dev.txt && pytest -q` | 52 passed |

Live mode was not exercised in the fresh copy (the dummy key cannot call the gateway); live behaviour is verified separately with the real key (see `output/evals/`).
