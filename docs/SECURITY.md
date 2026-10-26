# Security, privacy, and access boundary

## Access boundary of this prototype

- The server binds to **127.0.0.1** only. There are **no user accounts**: anyone who can use this computer account can use the app and read the database.
- Internal data (programs, budgets, transactions, notes) stays in `data/*.db` on this computer. Public research is cached separately in `data/public_research_cache.db`.
- Data leaves the computer in two ways only: (1) public-source requests built from the confirmed, non-confidential profile; (2) model requests to the configured provider (Portkey → gpt-6-luna), which receive only the context a task needs (for example, the classification text you typed, or tool results the Planning Assistant requested).

## Threats and controls

| Threat | Control | Tested in |
|---|---|---|
| Retrieved text tells the agent to reveal secrets, upload data, or change records | Untrusted-content framing; quarantine of instruction-like items; line scrubbing; agents have no write, shell, filesystem, SQL or upload tools; candidate-only fetching; output secret filter; read-only DB for tools | `test_safety.py` (simulated compromised model), `evals/run_evals.py injection` (live) |
| Model output is malformed or fabricated | Pydantic validation with retries; fabricated item ids dropped; passages kept only if verbatim; assistant figures and URLs grounding-checked | `test_safety.py`, evals |
| Runaway loops or cost | Per-run request/tool/token limits, per-tool caps, timeouts, daily run/token/cost limits | `test_safety.py` |
| SSRF via retrieval | http/https on default ports only; no credentials in URLs; DNS must resolve to public IPs; connection pinned to the vetted IP (SNI preserved); every redirect re-validated; size, time and concurrency limits | `test_safety.py` |
| Confidential data in public queries | Queries built only from public profile fields; guard rejects program codes, configured confidential terms, company name, amounts, long numbers, emails | `test_safety.py` |
| Malicious spreadsheets | `.csv`/`.xlsx` only; size/row limits; `.xlsm/.xls/.xlsb` rejected; openpyxl read-only, data-only (formulas not evaluated, macros not executed); formula-like text flagged | `test_imports.py` |
| CSV formula injection on export | Text cells beginning with `= + - @ \t \r` are prefixed with `'` | `test_imports.py` |
| XSS from retrieved text | React escapes all text; no `dangerouslySetInnerHTML`; CSP `default-src 'self'`; links `rel="noopener noreferrer nofollow"` | code review |
| Key exposure | Keys only in server environment; status shows presence and origin, never values; `redact()` applied to errors and traces; output secret filter | `test_safety.py` |
| Wrong model or provider | Course key locked to gpt-6-luna; personal OpenAI requires explicit model; no fallback | `test_safety.py` |
| Silent changes to plans | Agents propose actions/flags only; budgets, approvals, milestones and baselines change only through user actions, all logged in the activity log | tests + activity log |

## Before any shared or hosted deployment (not done)

1. Authentication (SSO or passwords + MFA) and session management.
2. Authorization enforced in the backend: roles (viewer, editor, finance approver, admin), per-endpoint checks, approval workflow for budgets.
3. HTTPS/TLS, CSRF protection for cookie sessions, rate limiting.
4. Postgres with encrypted storage and backups; per-tenant isolation; audit log immutability.
5. Secrets manager (no `.env` files on servers); key rotation.
6. A data-processing review of what goes to the model provider, and provider data-retention settings.
7. Security logging/monitoring and dependency scanning.

Never expose port 8000 to a network or tunnel in its current form.
