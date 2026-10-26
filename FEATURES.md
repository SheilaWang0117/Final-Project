# Feature checklist

Status as of 2026-10-24. ✅ implemented and verified · 🟡 partially implemented (limits stated) · ⬜ planned, not built.

## Navigation and language
- ✅ Question-based navigation groups with one-line hints, page headers stating each page's question, "You are here" trail, tab hints
- ✅ Overview mission and values banner ("All life matters"; mission editable in Settings) and eight question cards with live answers
- ✅ English / Simplified Chinese toggle for all UI text, status labels, warnings and chart legends; assistant and classification answer in Chinese
- 🟡 Stored research text (public-source titles and summaries) is shown in its original language; Chinese translation of research outputs is not automatic
- ✅ Cat and dog SVG touches (logo, banner, loading, empty states, briefing popup)

## Pipelines and onboarding
- ✅ Create, view, edit, search, filter (use, status), archive/unarchive programs
- ✅ Full profile: code, name, description, therapeutic area, indication, human/veterinary/unknown, species, target, mechanism, modality, molecule category, route, stage template + stage, status, owner, priority, jurisdictions, public keywords, risks, notes
- ✅ Separate veterinary and human stage templates
- ✅ AI classification: proposal with per-field basis (stated / inferred / unknown), verbatim evidence (non-verbatim quotes removed), follow-up questions, regulatory caution; user edits and confirms; nothing applied without confirmation
- ✅ Milestones with planned/baseline/actual dates, dependencies (cycle check), decision points, owners, notes; baseline set explicitly and logged; slip vs baseline shown
- ✅ Development phase map: pipelines × 12 veterinary development phases (FDA CVM INAD/phased review, EU 2019/6), value-inflection decision gates (passed / next / ahead), milestone status, overdue and funding gaps; phase from the Stage field or inferred from the name
- 🟡 Key dates are stored but have no dedicated editor (milestones cover the demo journey)

## Budgets, imports, cash and runway
- ✅ Milestone budget lines: category, currency, planned/approved, contingency, owner, estimate source, assumptions, monthly cash-out schedule; approve/re-approve/close; drafts deletable, approved lines not
- ✅ Shared company costs with explicit allocation rules (must total 100%); unallocated and unruled shared spend kept visible
- ✅ CSV/XLSX import: upload → sheet → header row → mapping → validation (dates incl. ambiguous d/m, currencies incl. ambiguous "$", amounts incl. parentheses/decimal comma) → duplicates (in-file and vs ledger, same-file re-upload warning) → rule-based category/program/milestone/kind suggestions → commitment matching → reconciliation summary (per currency) + optional statement check → explicit commit
- ✅ Original values and source-row references preserved; batches reversible without deleting audit history (commitments reopened)
- ✅ Refunds, financing inflows, transfers, shared expenses handled explicitly; transfers excluded from burn/income; intercompany matching incl. cross-currency (within 1%)
- ✅ Decimal / integer-minor-unit arithmetic, ROUND_HALF_UP, tested; no LLM arithmetic
- ✅ Gross and net operating burn, simple runway (suppressed when burn ≤ 0), dated forecast runway (below reserve / below zero)
- ✅ Cash requires reconciled balances; partial imports never become the cash balance; incomplete state shown
- ✅ Commitments separate from actuals; linking payment prevents double counting
- ✅ HKD, CNY, USD (+EUR for ECB crosses); manual rates; ECB reference rates; per-transaction conversion with source/date/method; missing rates excluded and reported; stale rates flagged
- ✅ Actual spend to date vs. estimate to complete for every milestone of each pipeline (unbudgeted milestones say "no budget yet"; company running costs shown separately), monthly flows chart, forecast chart, upcoming commitments, cost-to-reach next milestone, funding gap and timing. Variance on approved lines only is kept in the API and CSV export. The completeness checks still run (figures show as incomplete, the assistant lists gaps) but no longer have their own panel
- ✅ Base / accelerated / conservative / custom scenarios (milestone shifts with dependents, category cost changes, hypothetical financing, extra monthly cost); computed on copies; baseline untouched (tested)
- ✅ CSV export of summary + definitions + assumptions + scenarios, and of transactions (formula-injection safe)
- 🟡 Commitment-to-payment linking is suggested at import (exact counterparty and amount) and manual afterwards; partial payments are not split automatically
- 🟡 Multi-entity view is a management aggregation; per-entity filtering exists in the calculation layer but not as a UI selector

## Competitor intelligence and briefing
- ✅ Competitors by pipeline (default view): each competitor, its product and its latest captured movement; related news not tied to a named competitor shown separately
- ✅ Manual competitors; AI-suggested competitors (track/dismiss)
- ✅ Events with source, publication date, retrieval time, program, relevance + reason; observed vs interpretation vs labeled hypothesis vs suggested action
- ✅ URL canonicalization and near-duplicate title detection; change detection by content hash; "new since last check"
- ✅ Follow-ups queue (owner, priority, due date, status); agents only propose
- ✅ Daily briefing: lead story by an explained formula, animal-health, regulatory, pipeline sections, internal milestone/finance reminders; once-per-day dismissible popup; history; stale label; timezone setting
- ✅ Scheduled job (CLI + launchd/cron instructions) and manual refresh; in-app scheduler while running
- 🟡 Competitor events come from the sources searched (Europe PMC, ClinicalTrials.gov, SEC full-text, news feeds); no paid news or deal databases; paraphrased duplicate stories are not always merged (recall 0.6 on the eval set)

## Regulatory intelligence
- ✅ Registry of authorities per jurisdiction × product type (US, EU, CN, JP, KR; extensible), including FDA CVM vs USDA CVB caveat and MARA (not NMPA) for China veterinary products
- ✅ Retrieval from FDA guidance index, Federal Register, EMA document catalogue; link scanning of MARA, MAFF/NVAL, APQA, PMDA, MFDS pages
- ✅ Per document: title, original title, authority, jurisdiction, URL, dates, draft/final/unknown (from metadata), binding/guidance/unknown (from source type), verbatim-verified passages, retrieval date, content hash/version, applicability, open questions, AI summary/translation label
- ✅ Change detection and milestone flags for review (plans never changed automatically); review status
- ✅ Coverage view: sources, last successful check, failures, manual-only sources
- 🟡 Asian regulators: index-page links only (no full-text search); NMPA and USDA APHIS block automated access and are listed as manual checks; superseded status is not detected automatically

## Markets and licensing
- ✅ Reported annual revenue from SEC XBRL (Zoetis, Elanco, Phibro) as a comparable-revenue chart with definition, geography, period, metric, currency, source, coverage, value type
- ✅ Donut charts only for compatible market-share datasets (none available from free sources, so none shown)
- ✅ Partner candidates with evidence per criterion (Europe PMC affiliations, SEC filings, captured events, user-supplied URLs), deterministic fit score, labeled AI assessment, gaps
- ✅ User-supplied public URL research (SSRF-safe)
- 🟡 Indication-level market size/share is not available from free sources; filters by indication/species apply only when such observations exist
- 🟡 SEC filing text requires `SEC_USER_AGENT` with a contact (SEC policy); without it, partner evidence relies on publications and events

## Agents, safety, measurement
- ✅ Five roles in one backend with typed tools and validated structured outputs; read-only DB for tools; execution traces (tools, sources, durations, errors)
- ✅ Untrusted-content framing, quarantine of instruction-like retrieved text, candidate-only fetching, SSRF-safe retrieval (IP pinning, redirect checks), output secret filter, confidential query guard, per-run and daily limits, timeouts, retries, bounded concurrency
- ✅ Adversarial tests (simulated compromised model) and live injection evaluation; malformed output, unavailable sources, excessive tool calls tested
- ✅ Usage records: provider, model, input / provider-cached input / output / reasoning tokens, tool calls, latency, app cache hits, gateway cache hits, errors, cost from a dated pricing file (unknown if price missing)
- ✅ Reproducible evals (classification, finance, citations/regulatory relevance, dedupe, injection, limits, cached vs uncached)
- 🟡 Pricing for gpt-6-luna is from third-party sources, not verified against course billing

## Not built (planned)
- ⬜ User accounts, roles and backend-enforced permissions (local single-user prototype; see docs/SECURITY.md)
- ⬜ Hosted deployment (Postgres, HTTPS, secrets manager, worker queue)
- ⬜ Paid search/news integrations (optional; would need extra credentials)
- ⬜ Accounting-system connectors (Xero/QuickBooks) and bank feeds
- ⬜ Measured user-testing results (protocol ready in docs/user_testing_protocol.md; no sessions run yet)
