# Engineering harness

What is actually built, how it runs, how it is checked, and what is limited. Updated 2026-10-24.

## 1. Architecture

```
React + Vite + TypeScript (Recharts)  ──HTTP /api──►  FastAPI (single process, 127.0.0.1:8000)
                                                       ├─ api/          routers: pipelines, finance, imports, intel, system
                                                       ├─ finance/      money, fx, calc (pure functions), ledger (DB→inputs), imports
                                                       ├─ agents/       PydanticAI agents, typed read-only tools, runner, prompts/
                                                       ├─ research/     safe HTTP, public cache, query guard, injection quarantine,
                                                       │                dedupe, registry, connectors/
                                                       ├─ jobs/         background jobs (asyncio) + daily CLI
                                                       └─ demo/         synthetic seed + labeled fixtures
SQLite: data/<mode>.db (internal, confidential)     SQLite: data/public_research_cache.db (public content only)
External: Portkey gateway → gpt-6-luna (Responses API); public sources listed below
```

No microservices, queues, or vector databases. Background research runs as asyncio tasks inside the API process, with status persisted in `jobs`; the daily CLI (`python -m app.jobs.daily`) runs the same functions.

### Data model (migrations in `backend/app/migrations/`)
Programs, classification proposals, milestones; legal entities, cash accounts, reconciled balances, FX rates, budget lines + monthly schedules, allocation rules, import batches + staged rows, transactions (original row JSON, source row, dedupe hash, reversed flag), commitments, planned flows, scenarios; competitors, intel events, actions, briefings, briefing views; regulatory sources, documents, assessments; market observations, partner candidates; jobs, agent runs (usage, trace, sources, cache and gateway statistics), activity log. Money is stored as integer minor units with a currency; rates as decimal strings.

## 2. Deterministic finance (`backend/app/finance/calc.py`)

- Cash = latest reconciled balance per active account + transactions after that date. Missing balance → incomplete (never derived from imports).
- Gross burn = operating outflows / months; net burn = (operating outflows − operating inflows incl. refunds) / months. Financing and transfers excluded; intercompany transfer pairs matched (cross-currency within 1%).
- Simple runway = cash / net burn when net burn > 0, otherwise "not depleting".
- Remaining forecast per (program, milestone, category) = max(0, (approved or planned) × (1 + contingency) × scenario factor − paid actual − open commitments). Done/cancelled/closed → 0.
- Forecast: remaining cost spread over each line's future schedule (or evenly to milestone end), commitments at expected payment month, confirmed planned flows; hypothetical flows only in scenarios. Runway = first month below reserve / below zero.
- Milestone funding: direct cost of the milestone and its unfinished prerequisites; funded if projected month-end cash ≥ reserve through the milestone's end month; unknown if nothing in the chain is budgeted.
- Scenarios: deep copies; milestone shifts propagate to dependents; category cost factors; hypothetical financing; extra monthly cost.
- FX: direct, inverse, or EUR cross (ECB) rate dated on or before the transaction; manual rates win ties; missing rates excluded and listed; stale (>10 days) flagged. ROUND_HALF_UP to minor units.

## 3. Agents and typed tools

| Agent | Inputs it may see | Tools | Output (validated) | Writes (by app code, after validation) |
|---|---|---|---|---|
| Pipeline Classification | the user's description | none | `ClassificationProposal` (per-field value, stated/inferred/unknown, verbatim evidence, follow-ups, caution) | proposal only; profile changes only on user confirmation |
| External Intelligence | confirmed public profile, tracked competitor names, retrieved candidates (untrusted blocks) | `read_candidate(item_id)` (cap 3; only listed candidates) | `IntelligenceReport` / `BriefingDraft` | events (dedupe/change detection), suggested competitors, proposed actions, briefing |
| Regulatory Research | confirmed public profile, open milestone names/ids, candidate official documents | `read_document(doc_id)` (cap 4) | `RegulatoryReport` | documents (status/binding from metadata), assessments, verbatim passages only, review flags/actions |
| Market and Partner | public profile, evidence items per company | none | `PartnerReport` | partner candidates; fit score computed by code from cited evidence |
| Planning Assistant | the question | `get_pipeline`, `list_milestones`, `get_budget_summary`, `calculate_cash_forecast`, `check_milestone_funding`, `simulate_milestone_delay`, `compare_scenario`, `list_scenarios`, `get_competitor_events`, `get_regulatory_documents`, `get_market_observations`, `list_partner_candidates` | `AssistantAnswer` (answer, key figures with tool, sources, assumptions, gaps, suggestions) | none; figures and URLs are grounding-checked |

Market observations (SEC XBRL revenue) are stored deterministically with no model call. All tools open SQLite read-only (`mode=ro`). Model: `gpt-6-luna` via `https://api.portkey.ai/v1`, `OpenAIResponsesModel` (Responses API).

Runner (`agents/runner.py`): per-run request/tool/token limits (`UsageLimits`), timeout, daily run/token/cost limits, per-tool caps, structured-output validation with retries, output secret filter, gateway-cache capture, trace of tools/sources/durations/errors (no prompts or hidden reasoning stored).

Demo mode: rule-based classifier, template assistant answers from the same tools, fixtures for research (example.org URLs, labeled). Demo runs record no tokens.

## 4. Public sources (verified 2026-10-24)

| Connector | Source | Used for |
|---|---|---|
| `search_clinicaltrials` | ClinicalTrials.gov API v2 | trial registrations (human; comparative oncology context) |
| `search_europepmc` | Europe PMC REST | publications; company-affiliation evidence |
| `search_federal_register` | Federal Register API (FDA, APHIS) | rules, proposed rules, notices |
| `search_fda_guidance` | FDA guidance-document index (JSON) | CVM / CDER / CBER guidance with draft/final |
| `search_ema_documents` | EMA documents catalogue (JSON) | CVMP / CHMP guidelines with status |
| `fetch_feed` | Fierce Biotech, BioPharma Dive, STAT, FDA press, EMA news, Veterinary Practice News, dvm360 | news, briefing |
| `sec_annual_revenue`, `sec_full_text` | SEC XBRL company concepts; EDGAR full-text search | reported revenue; filing evidence |
| `scan_index_page` | MARA notices, MAFF/NVAL, APQA, PMDA, MFDS | link-level regulatory coverage (original-language titles) |
| `fetch_reference_rates` | ECB euro reference rates | FX |
| `fetch_document_text` | any approved candidate URL (HTML/PDF) | full text for reading and passage verification |

Checked and excluded: Endpoints News feed (403), USDA APHIS site (403 → via Federal Register), NMPA (412 → manual), IVDC (intermittent timeouts), EMA veterinary medicines JSON (holders blank). SEC filing documents need `SEC_USER_AGENT`.

## 5. Caching (three layers)

1. **Application retrieval cache** (`public_research_cache.db`): public responses by URL with TTL (default 20 h; FDA/EMA indexes 24 h); hit/miss counted per run; content versions for change detection. Shared safely because it holds only public content.
2. **Gateway response cache** (Portkey): identical requests can be replayed (`x-portkey-cache-status: HIT`), recorded per run. All-hit runs are costed at $0 (billing unverified). Evaluations send `x-portkey-cache-force-refresh`.
3. **Provider prompt caching**: provider-reported cached input tokens, recorded per run and priced at the cached rate.

## 6. Security controls

Untrusted-content framing; quarantine of instruction-like retrieved text and line scrubbing; agents have no shell, filesystem, SQL, or write tools; candidate-only fetching; SSRF-safe retrieval (scheme/port/credential checks, DNS → public IPs only, IP pinning with SNI, redirect re-validation, size/time caps, retries, concurrency limit); confidential query guard (program codes, confidential terms, amounts, emails); public profile only in external queries; parameterized SQL; React rendering (no raw HTML); CSP and security headers; upload type/size/row limits; formulas never evaluated, macro files rejected; CSV export formula-injection protection; secrets server-side and redacted from logs/traces/errors; output secret filter; usage and spending limits. Details: `docs/SECURITY.md`.

## 7. Setup

See README. Tested with Python 3.14.7, Node 24.21, npm 11.19 on macOS. Pinned: `backend/requirements.txt` (runtime), `backend/requirements-dev.txt` (pytest, Playwright), `frontend/package-lock.json`.

## 8. Checks run (2026-10-24)

| Check | Result |
|---|---|
| Backend tests (`pytest -q`) | 52 passed (finance 22, imports 9, API smoke 4, import API end-to-end 1, safety 16) |
| Frontend typecheck + production build | passed (`tsc --noEmit`, `vite build`) |
| Live connector check | all listed connectors returned data; exclusions above |
| Live agents | all five roles ran against gpt-6-luna; see `output/evals/results.json` |
| Browser journey (`scripts/capture_journey.py`, live mode, synthetic records) | 23 screenshots (rerun 2026-10-26 on a freshly seeded three-pipeline workspace), no browser console errors |
| Evaluations | `output/evals/summary.md` |
| Fresh install with dummy `../.env` | see `output/fresh_install_check.md` |
| Daily job CLI | briefing + 2× competitor + 2× regulatory jobs succeeded (demo DB) |

## 9. Current limitations

- Local single-user prototype; no accounts or permissions. Do not expose it to a network (see `docs/SECURITY.md`).
- Research coverage is limited to listed sources; competitor events skew to publications; no paid news/deal databases; paraphrased duplicates may remain.
- Asian regulators covered at link level only; NMPA/APHIS manual; superseded status not detected.
- Market data: company total revenues only (no indication-level market size or share).
- Partner fit scores measure documented evidence and cluster when evidence is generic; they are not deal likelihood.
- Pricing for gpt-6-luna comes from third-party pages, not course billing; gateway cache-hit billing unverified.
- Classification and relevance evaluations are small and labeled by the builder.
- The heuristic injection quarantine can miss disguised instructions; other layers remain.
- Forecast assumes FX at the as-of date and month-level timing.
