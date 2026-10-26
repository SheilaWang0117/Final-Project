# Cost model (estimates)

All monthly figures are **estimates** built from measured per-run usage (2026-10-24 and the 2026-10-25 journey rerun, gpt-6-luna via Portkey, gateway cache bypassed) and the dated price table in `backend/app/agents/pricing.json`: **$0.10 per 1M input tokens, $0.01 per 1M cached input tokens, $0.50 per 1M output tokens** (third-party sources; not verified against course billing). Change the price file and these numbers scale linearly.

## Measured cost per run (uncached at the gateway)

| Run | Typical tokens (in / provider-cached / out) | Est. cost per run |
|---|---|---|
| Classification | 1.4K / 0–1.3K / 0.6–1.0K | $0.0004–0.0006 (use $0.0004) |
| Competitor refresh (one program) | 10–13K / 5–10K / 0.9–1.6K | $0.0008–0.0017 (use $0.0012) |
| Regulatory refresh (one program) | 8–16K / 5K / 1.5–3.5K | $0.0012–0.0029 (use $0.0024) |
| Daily briefing (company) | 4.3–4.4K / 0 / 1.2–1.4K | $0.0010 |
| Partner assessment (one program) | 3.1K / 3.0K / 1.9K | $0.0010–0.0013 (use $0.0012) |
| Planning Assistant question | 5–13K / 2–7K / 0.4–1.2K | $0.0005–0.0013 (use $0.0010) |

Source: `agent_runs` in `data/eval_live.db` and `data/class_demo.db`; `output/evals/results.json`.

## Workload assumptions

- A company has **3 active confirmed programs**.
- Shared research per company per day: 1 briefing + per program 1 competitor refresh + 1 regulatory refresh; partner assessment weekly.
- Per user: 10 assistant questions per working day (21.7 days/month); classifications negligible.
- No paid search provider (all sources are free public APIs).

## Monthly estimates

| | 1 user (1 company) | 100 users (20 companies × 5) | 10,000 users (2,000 companies × 5) |
|---|---|---|---|
| Shared daily research | $0.37 | $7.4 | $740 |
| Per-user chat | $0.22 | $22 | $2,170 |
| **Model total** | **≈ $0.6** | **≈ $29** | **≈ $2,900** |
| Hosting (assumption) | $0 (local laptop) | $50–100 (small VM + managed Postgres + backups) | $1,500–4,000 (several app instances, Postgres, job workers, monitoring) |
| Optional paid search (assumption) | $0 | $0 | $3,600–10,800 if a commercial search API at $5–15 per 1,000 queries replaced free sources (4 queries × 3 programs × 2,000 companies × 30 days = 720K queries) |

Calculation of shared research per company per day: $0.0010 + 3 × ($0.0012 + $0.0024) + 3 × $0.0012 / 7 ≈ $0.0123 → ≈ $0.37 per 30-day month.

## What changes the picture

- **Gateway response cache**: identical requests replay at no model cost (observed), but replays also repeat old judgments. Daily research prompts change with new content, so few hits are expected in production.
- **Provider prompt caching** covered 0% (briefing, single request) to about 95% (competitor refresh) of input tokens in measured runs; multi-step runs reuse the prompt prefix.
- **Application cache**: reduces latency (14.3 s → 12.8 s in the measured comparison; most time is the model) and public-API load, not model tokens.
- **Scale risk**: free public APIs have rate limits (e.g., SEC, NCBI). At 2,000 companies, the shared public cache and per-source schedulers become necessary; that is engineering cost, not API cost.
- Reasoning tokens are billed as output; long regulatory documents increase input tokens (capped at 9,000 characters per document read, 4 reads per run).
