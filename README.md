# Ocra Pipeline Tracker

A local operating tool for a small veterinary-oncology biotech team. It connects **pipeline development → milestone budgets → cash runway → external developments → reviewable decisions**, so the team can answer: *can we fund the next scientific milestone, and what new information could change that?*

- **Deterministic finance**: decimal/minor-unit calculations for cash, gross/net burn, simple and forecast runway, milestone funding, scenarios, and imports (no LLM arithmetic).
- **Small agent team** (PydanticAI, one backend): Pipeline Classification, External Intelligence (competitors + daily briefing), Regulatory Research, Market and Partner, and a Planning Assistant with read-only typed tools.
- **Real public sources, no paid search key**: ClinicalTrials.gov, Europe PMC, Federal Register, FDA guidance index, EMA document catalogue, SEC EDGAR, ECB reference rates, regulator index pages (MARA, MAFF/NVAL, APQA, PMDA, MFDS) and biotech/veterinary news feeds.
- **Provenance everywhere**: internal, imported, external source (with link and dates), AI interpretation, planning assumption, synthetic demo, and demo fixture are labeled separately.

Screens, architecture, evidence and limits: `report.html` · Slides: `slides.html` · Engineering harness: `output/harness.md` · Feature checklist: `FEATURES.md`.

---

## 1. Prerequisites

- macOS or Linux, **Python 3.12+** (tested with 3.14.7), **Node.js 20+** (tested with 24.21) and npm.
- Optional: Google Chrome (only for the screenshot/journey script).
- For live mode: the course `PORTKEY_API_KEY` (used only with `gpt-6-luna`) or a personal `OPENAI_API_KEY` with an explicit `OPENAI_MODEL`.

## 2. Install (about 5 minutes)

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
```

Optional development tools (tests, screenshots):

```bash
.venv/bin/pip install -r backend/requirements-dev.txt
```

## 3. Configure

Configuration is read relative to the repository, independent of the working directory:

1. variables already set in your environment win;
2. then `./.env` in this repository;
3. then `../.env` **one directory above the repository** fills anything still missing.

```bash
cp .env.example .env      # or keep your keys in ../.env
```

| Variable | Purpose |
|---|---|
| `APP_MODE` | `demo` (default: synthetic data + labeled fixtures, no keys) or `live` |
| `LLM_PROVIDER` | `portkey` (default), `openai`, or `none` |
| `PORTKEY_API_KEY` | Course key. Gateway `https://api.portkey.ai/v1`, model fixed to `gpt-6-luna`; any other model is refused |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional personal provider; both must be set explicitly |
| `SEC_USER_AGENT` | Optional "Company contact@email" string; required by SEC to read filing documents (revenue facts work without it) |

The app never switches providers or models silently, never logs keys, and keeps keys server-side.

## 4. Run

**Demo mode** (works without any API key):

```bash
APP_MODE=demo scripts/start.sh
# open http://127.0.0.1:8000
```

The demo database (`data/demo.db`) is created on first start with **hypothetical programs** (HX-101, HX-205, HX-310) and synthetic financial records that do not describe any real pipeline and uses a fixed as-of date (2026-10-24). Settings → *Reset demo data* restores it.

**Live mode** with your own (empty) company database:

```bash
APP_MODE=live scripts/start.sh            # uses data/ocra_live.db
```

**Live class demo** (real retrieval and model calls, synthetic internal records, separate database):

```bash
cd backend
APP_MODE=live DATABASE_PATH=data/class_demo.db ../.venv/bin/python -m app.demo.seed --into-current
cd .. && APP_MODE=live DATABASE_PATH=data/class_demo.db scripts/start.sh
```

Frontend development with hot reload (optional): run the backend as above, then `cd frontend && npm run dev` and open http://127.0.0.1:5173 (Vite proxies `/api`). The server is started without auto-reload, so one edit never spawns extra servers. Stop it with Ctrl-C (or `pkill -f "uvicorn app.main:app"`, which stops the whole process).

## 4b. Navigation, mission, and language

- The sidebar is grouped by the question a manager brings: **Start here** (Overview) · **Our science** (Pipelines) · **Our money** (Budget and Runway) · **Outside world** (Daily Briefing, Competitors, Regulatory, Markets) · **Get help** (AI Assistant, Settings). Each item shows a one-line hint, every page header states the question it answers, and a "You are here" trail sits at the top.
- The Overview opens with the company's mission and values ("All life matters") and eight "What do you want to know?" cards, each with a live one-line answer that links to the right page. Edit the mission and values in Settings → Mission and values (a draft mission is shown until you write your own).
- **EN / 中文** toggle in the sidebar and top bar (remembered in the browser; `?lang=zh` or `?lang=en` also work). All interface text, status labels, warnings and chart legends are translated. The AI Assistant and the classification agent answer in Chinese when 中文 is selected. Stored research text (source titles, summaries from public sources) stays in its original language.
- The sidebar fits the window without scrolling (hints hide automatically on short screens).
- Pipelines shows a **development phase map**: pipelines as rows, twelve veterinary development phases as columns (discovery → lead optimization → patent filing → preclinical/PK → CMC → INAD/advice → GLP target animal safety → pilot and pivotal GCP field studies → dossier → approval → launch), with a diamond decision gate at each value-inflection point (`backend/app/phases.py`, `/api/phase-map`).
- Budget and Runway → Summary shows, for each pipeline, every milestone's actual spend to date against its estimate to complete (open commitments + remaining budget). Competitor Intelligence opens on one card per pipeline: competitor, product, latest movement.
- **Manager guide:** [USER_MANUAL.md](USER_MANUAL.md).
- Small cat and puppy drawings (inline SVG, no image files) appear in the logo, the mission banner, loading indicators, and empty screens.
- The mission title uses Fredoka (bundled locally via `@fontsource/fredoka`, SIL Open Font License); in Chinese it uses the system 楷体 (Kaiti), falling back to 宋体 (Songti).

## 5. Daily refresh

Research runs on a schedule or manual refresh, not on every visit.

- **While the app runs** in live mode, an in-app scheduler builds the daily briefing once after `BRIEFING_HOUR` (default 07:00, `APP_TIMEZONE`, default Asia/Hong_Kong). Disable with `ENABLE_SCHEDULER=false`.
- **Scheduled job**: `scripts/run_daily.sh` runs the briefing plus competitor and regulatory refresh for every confirmed active program (`python -m app.jobs.daily`). On macOS, install `scripts/com.ocra.pipeline.daily.plist.example` with launchd (instructions inside), or use cron: `15 7 * * * /path/to/scripts/run_daily.sh`.
- A closed or sleeping laptop does not collect updates. The app then shows the most recent briefing with a visible **stale** label.

## 6. Tests and evaluations

```bash
cd backend && ../.venv/bin/python -m pytest -q          # 49 tests: finance, imports, API, safety
cd .. && .venv/bin/python evals/run_evals.py dedupe finance safety          # offline
APP_MODE=live .venv/bin/python evals/run_evals.py       # adds live sections (needs a key; a few cents)
cd frontend && npm run typecheck && npm run build
```

Results: `output/evals/results.json` and `output/evals/summary.md`. Evaluations use their own synthetic database (`data/eval_live.db`) and bypass the Portkey response cache so model behaviour is measured fresh.

Screenshots of the full journey: start a live class demo (above) and run `.venv/bin/python scripts/capture_journey.py`.

## 7. Importing financial data

Budget and Runway → Import: upload CSV/XLSX → choose worksheet → map columns → validate → review flags and rule-based suggestions → reconciliation summary (optional bank-statement check) → **confirm** to commit. Templates and synthetic samples are downloadable on that page (`sample_data/`). Batches can be reversed; reversed transactions stay for audit. Imports never set the cash balance: record reconciled balances under *Cash, FX and settings*.

## 8. Backup and export

- `scripts/backup.sh [db]` writes a consistent SQLite copy to `data/backups/` (contains confidential data; store securely).
- Budget and Runway → *Export summary + assumptions (CSV)* and *Export transactions (CSV)*; exported text cells are protected against spreadsheet formula injection.
- The public research cache (`data/public_research_cache.db`) holds only public content and can be deleted at any time.

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| "Cannot reach the backend" | Start the server; check port 8000 is free (`lsof -i :8000`). |
| "Model not ready" in live mode | Set `PORTKEY_API_KEY` (env, `./.env`, or `../.env`) and restart. `PORTKEY_MODEL` must be `gpt-6-luna`. |
| Research button disabled | Confirm the program profile first (Pipelines → program → Propose/confirm profile). |
| A source shows "failed" | See Regulatory → Authorities and coverage, or the run trace. Some sites block automated access (USDA APHIS, NMPA); they are listed as manual checks. |
| Content-filter error on a research run | A retrieved page contained instruction-like text; nothing was saved. Re-run; the quarantine layer withholds such pages. |
| Cash shows "Incomplete" | Add a reconciled balance (date + amount) for every active account. |
| Runway seems too long | Compare the simple runway (past spending) with the forecast (planned studies and commitments); import recent transactions. |

## 10. Known limitations (summary)

Local single-user prototype without accounts; research coverage is limited to the listed sources; Chinese, Japanese and Korean regulator coverage is link-level from index pages; partner fit scores measure documented evidence, not deal likelihood; costs use a third-party, unverified price for `gpt-6-luna`. Full list: `output/harness.md` and `report.html`.

## 11. Repository map

```
backend/app/        FastAPI app: api/ (routers), finance/ (deterministic calculations, imports),
                    agents/ (PydanticAI agents, typed tools, prompts, runner), research/ (safe fetch,
                    cache, guard, connectors), jobs/ (background + daily), demo/ (synthetic seed, fixtures),
                    migrations/ (SQL)
backend/tests/      pytest suites
frontend/src/       React + Vite + TypeScript UI (Recharts)
evals/              labeled cases and the evaluation runner
sample_data/        import templates and synthetic files
scripts/            start, daily job, backup, launchd example, sample-data and screenshot scripts
docs/               security, cost model, user-testing protocol, comparison, demo script
output/             harness.md, evals/, screenshots/
report.html, slides.html, AI_prompts.md, FEATURES.md, SUBMISSION_CHECKLIST.md
```
