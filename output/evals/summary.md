# Evaluation summary

Generated 2026-10-26T01:54:51.788152+00:00 · provider portkey · model gpt-6-luna

- **Classification** field accuracy: live 0.95, rule-based 0.925 (10 descriptions incl. ambiguous ones). Target left unknown when unstated: [True, True].
- **Financial calculations and imports**: 32 passed in 0.77s.
- **Duplicate detection**: precision 1.0, recall 0.6 (tp 3, fp 0, fn 2, tn 5). Misses are paraphrased headlines.
- **Regulatory relevance** on 20 labeled FDA CVM guidance titles: precision 1.0, recall 0.8; passages returned 4, verbatim-verified 4.
- **Prompt injection** (5 variants, live model, quarantine layer bypassed): secrets leaked 0, protected records changed 0, flagged by the model 4, rejected by the provider content filter 1. Quarantine layer would withhold 5/5.
- **Safety unit tests** (simulated compromised model, limits, SSRF, guard): 16 passed in 0.73s.
- **Planning Assistant grounding**: 4 questions, unverified figures 0.
- **Cache · cold app cache no gateway cache**: 15.81 s; app cache 0 hits / 11 fetches; gateway cache 0 hits / 2 misses; input tokens 10577 (provider-cached 5029); output 617; est. cost $0.000914; events new/unchanged 1/0.
- **Cache · warm app cache no gateway cache**: 7.8 s; app cache 9 hits / 1 fetches; gateway cache 0 hits / 2 misses; input tokens 10395 (provider-cached 10058); output 438; est. cost $0.000353; events new/unchanged 0/1.
- **Cache · warm app cache gateway cache allowed**: 1.08 s; app cache 9 hits / 1 fetches; gateway cache 2 hits / 0 misses; input tokens 10395 (provider-cached 10058); output 438; est. cost $0; events new/unchanged 0/1.
