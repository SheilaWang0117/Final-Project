# Timed user-testing protocol

Status: **Ocra's scientists already use the app, and their qualitative feedback shaped the latest changes (AI_prompts.md, iteration 15). No timed sessions have been run, so no time savings are claimed.**

## Goal
Measure whether the app shortens two recurring tasks for a small biotech team without lowering accuracy:
- **Task A — Milestone funding summary**: "Is the next milestone of program X funded? What is the cost to reach it, the lowest projected cash before it, and the main risks?"
- **Task B — Competitor and regulatory briefing**: "What changed this week that could affect program X? Give three items with sources and dates."

## Participants
2–5 people who would use the tool (e.g., CEO, finance lead, scientist). Each does both tasks once manually and once with the app, on different programs (counterbalanced) to limit learning effects. Use the synthetic class-demo workspace so no confidential data is involved.

## Materials
- Manual condition: the synthetic spreadsheet (`sample_data/synthetic_ledger_multi_entity.xlsx`), a budget table export, a web browser with normal search.
- App condition: live class-demo database (README §4), program pre-confirmed.
- Answer sheet with required fields; stopwatch.

## Procedure (per participant, ~60 minutes)
1. Two minutes of orientation for the app condition (no help during tasks).
2. Run Task A and Task B in both conditions, alternating the order between participants.
3. Stop the clock when the answer sheet is complete or at 20 minutes per task.
4. After each task: confidence (1–5) and perceived effort (NASA-TLX raw, 6 items) short form.
5. Debrief: what was missing, what was trusted or not, and why.

## Measures
- Time to complete (minutes).
- Accuracy against an answer key computed beforehand from the deterministic tools (funded yes/no, cost to reach within 1%, lowest cash month, ≥2 correct cited items with dates).
- Citation completeness (source link + date present).
- Errors of fact or unsupported claims.
- Confidence and effort scores.

## Analysis
Report per-participant times and accuracy in a table, medians, and the paired difference. With n < 10, describe results; do not claim statistical significance. Record any case where the app was wrong or misleading.

## Recording
Fill `output/user_testing_results.md` (create it after sessions): date, participant role (no names unless consented), condition order, times, accuracy, comments quoted only with permission.
