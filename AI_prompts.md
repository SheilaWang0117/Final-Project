# AI prompts and iterations

This file records how AI was used to build the project: the build prompt, the runtime agent prompts, and the iterations that changed the design. It contains no API keys and no confidential company data. All program, budget and transaction data in this repository is synthetic.

## 1. Build assistant

- Tool: Claude Code (model: Claude Opus 5.5), working as the software engineer on this repository, 2026-10-24.
- Claude is a development tool only. The application itself calls `gpt-6-luna` through the course Portkey gateway (or a separately configured OpenAI provider), never Claude.

### 1.1 Build prompt (summary of the brief given by Sheila Wang)

> Build a working application, from scratch, named **Ocra Pipeline Intelligence**, for a small veterinary-oncology biotech team. Connect pipeline development → milestone budgets → cash runway → external developments → reviewable decisions. Stack: FastAPI, React + Vite + TypeScript, SQLite, Pydantic, PydanticAI with narrow typed tools, a maintained chart library. Modules: Overview, Pipelines (with AI onboarding/classification), Budget and Runway (milestone budgets, CSV/XLSX imports with preview-and-confirm, deterministic burn and runway, FX, scenarios), Competitor Intelligence, Daily Briefing, Regulatory Intelligence (US, EU, CN, JP, KR), Markets and Licensing, AI Assistant, Settings and Activity. Distinguish internal, external, AI, assumption and synthetic data; cite sources with dates; never invent facts. Use only the course `PORTKEY_API_KEY` with gpt-6-luna; no silent provider switching; load `.env` from the repo and then one directory above. Implement prompt-injection defenses with a working adversarial test, measure tokens/cost/latency/caching, produce reproducible evaluations, a README, `report.html` (10–15 pages) and a reveal.js `slides.html` (≤10 slides). Do not deploy, publish, push, or contact anyone.

The full brief is kept by the author; the summary above captures every requirement used.

### 1.2 Course instructions applied

- Workspace `AGENTS.md`: load `PORTKEY_API_KEY` from the root `.env`; create a virtual environment inside the project folder; keep work inside the project folder; visuals in HTML/CSS; cozy color schemes; for any Dash app disable the reloader (this project uses FastAPI, started without `--reload`).
- Model name: `AGENTS.md` says "gpt-5.6 luna" but the final-project brief requires **gpt-6-luna** and the most recent homework used it, so the brief wins. A one-request probe confirmed the gateway accepts `gpt-6-luna` (resolving to `gpt-6-luna-2026-09-22`).

## 2. Runtime agent prompts

Stored as files so they can be reviewed and versioned (`PROMPT_VERSION` is recorded with every agent run):

| Agent | Prompt file | Output schema |
|---|---|---|
| Pipeline Classification | `backend/app/agents/prompts/classification.md` | `ClassificationProposal` |
| External Intelligence (competitors) | `prompts/intelligence.md` | `IntelligenceReport` |
| External Intelligence (briefing) | `prompts/briefing.md` | `BriefingDraft` |
| Regulatory Research | `prompts/regulatory.md` | `RegulatoryReport` |
| Market and Partner | `prompts/market.md` | `PartnerReport` |
| Planning Assistant | `prompts/assistant.md` | `AssistantAnswer` |
| Shared safety rules (appended to all) | `prompts/_safety.md` | — |

## 3. Iterations that changed the design

1. **Gateway rejected tools on chat completions.** The first live PydanticAI test failed: "Function tools with reasoning_effort are not supported for gpt-6-luna-global in /v1/chat/completions". Switched all agents to `OpenAIResponsesModel` (Responses API).
2. **Double counting of company costs.** Reviewing the demo forecast showed shared payroll/rent payments were not netted against company-level budget lines. Shared spend now counts against the shared pool; allocation to programs needs an explicit rule. Regression test added.
3. **"Funded" for unbudgeted milestones.** An unbudgeted, overdue milestone displayed as funded. Funding is now *unknown* when nothing in the dependency chain has a budget, and overdue milestones are tested through the current month.
4. **Overrun vs unapproved estimates.** Budget-vs-actual showed a large "overrun" that was really unapproved estimates. Variance is now computed only on approved lines; unapproved estimates are a separate column (also in the assistant's tool output).
5. **Partner evidence was empty metadata.** The partner agent (correctly) refused to score filings described only as "matched query terms". Evidence now includes real sentences/titles; SEC filing text requires an `SEC_USER_AGENT` contact (SEC's policy returned 403), so it is optional and the gap is shown. Also fixed a bug that dropped the Europe PMC date window.
6. **Regulatory coverage too narrow.** Candidates were cut by recency, hiding central guidance. Candidates are now ranked by term matches, then date; the prompt asks for every plausibly relevant document.
7. **Briefing balance.** First briefing contained only human-biotech stories; the briefing prompt now requires animal-health and regulatory items when available.
8. **Prompt-injection availability.** In live injection testing, Azure's content filter rejected one jailbreak-style page and failed the run (safe but disruptive). Added a quarantine layer that withholds instruction-like retrieved text before the model sees it, plus line scrubbing for full-text reads, and a clear "content filtered" status.
9. **Hidden gateway cache.** Evaluation runs returned in about 1 second with byte-identical token counts. Response headers showed `x-portkey-cache-status: HIT`: Portkey replays whole responses for identical requests. The app now records gateway cache hits per run, treats all-hit runs as $0 (billing unverified), and evaluations force a refresh so model behaviour is measured fresh.
10. **Secret leakage defence in depth.** Added an output filter: any agent output containing a configured secret is discarded and the run marked `blocked_secret` (tested with a simulated compromised model).
11. **Path bug during the build.** A relative `DATABASE_PATH=../data/...` created a database outside the project folder; it was removed immediately and paths are documented relative to the repository root.

12. **Manager navigation, mission, Chinese (2026-10-25).** Request: make the flow as easy to navigate as the earlier Dash tracker, show the mission and the value "All life matters" on the Overview, add cat and dog symbols, and add a Chinese version. Changes: question-based sidebar groups with hints, page headers stating the question each page answers, Overview question cards with live one-line answers, editable mission/values (a draft mission is shown until the team writes one), inline SVG cats and dogs, and an English/Chinese toggle covering every UI string (about 1,040 keys, checked by a script for gaps). The assistant and classifier receive a `language` field and answer in Chinese while keeping figures exactly as tools return them (grounding check still passes).
13. **Cuter pets and a mission font (2026-10-25).** Request (later reversed in iteration 14): make the dog a bulldog, make the cat cuter, and give the mission title a different font. The first bulldog draft read as a teddy bear, so it was redrawn with a wide flat face, folded rose ears, a fawn eye patch, a nose rope wrinkle, hanging jowls and an underbite; the cat got bigger sparkly eyes, pink ears and cheeks, tabby stripes and an "ω" smile. Mission title: bundled Fredoka (OFL) for English, system Kaiti for Chinese.
14. **Hypothetical pipelines and a cuter dog (2026-10-26).** Request: hide all important pipeline information and use hypothetical pipelines; make the dog cuter (not a bulldog). The demo portfolio, fixtures, evaluation cases, sample files, walkthrough and UI examples were replaced with hypothetical small-molecule programs (HX-101 canine mast cell tumor kinase inhibitor, HX-205 feline oral-tumor intralesional small molecule, HX-310 equine sarcoid cream) that do not resemble the company's real programs. Evaluation cases that came close to real work were replaced. All local databases and the public research cache were deleted and rebuilt; evaluations, screenshots, report and slides were regenerated. The dog is now a round golden puppy with floppy ears.
15. **Scientist feedback round (2026-10-25).** Feedback from Ocra's scientists, relayed by the author: the data completeness and reconciliation warnings panel was confusing; program-level budget versus actual was hard to read (they wanted three pipelines, comparing spending to date with future budget per milestone); the competitor page should simply show each pipeline's competitors, their products and latest movement; the sidebar should fit on one screen; managers need a user manual. Changes: the warnings panel was removed from the Overview and Budget pages (the checks still run and still feed the assistant's gaps); a new `pipelines` block in `/api/finance/summary` and a per-pipeline milestone spend view; `/api/competitors/by-pipeline` and a default "Competitors by pipeline" tab; a viewport-height sidebar that never scrolls; USER_MANUAL.md. The fourth demo program, created by the screenshot journey, was removed. The journey now shows the classification proposal without saving it, the workspace was reseeded, and the live journey, report and slides were regenerated.
16. **Phase map, naming and theme (2026-10-26).** Request: the milestone timeline should show development phases across the top (discovery, GLP, GCP, patent application and so on, researched and comprehensive) with the pipelines down the side, and a decision point at every value-inflection point. Also: rename the app to Ocra Pipeline Tracker, phrase "spent so far / still to spend" more professionally, and make the font and theme creative and techy. Research: FDA CVM's description of the approval path (INAD file, phased review of seven technical sections, protocol concurrence before pivotal studies, NADA), conditional approval under section 571 / GFI #261, and EMA's limited-market route under Regulation (EU) 2019/6 Art. 23 (horses qualify; dogs and cats do not). Changes: `backend/app/phases.py` defines twelve phases and seven value-inflection gates, and `/api/phase-map` places every milestone in a phase (Stage field first, then the name, then the older stage labels) and marks each gate passed / next / ahead. The date Gantt was replaced by a pipelines × phases matrix, with completed patent and INAD milestones added to the demo seed. Cost terms became "actual spend to date" and "estimate to complete". The app was renamed, and a "lab console" theme was added (bundled Space Grotesk and JetBrains Mono, SIL OFL). The demo workspace was reseeded, the live journey rerun, and the report and slides regenerated.

## 4. Prompts used for evaluation

Labeled cases are in `evals/cases.py` (classification descriptions, duplicate pairs, regulatory relevance keywords, five injection strings including Chinese). The injection strings are adversarial test data, not instructions.
