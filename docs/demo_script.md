# Demo video (about 2.5 minutes)

Written for: the course demo video. A recorded version exists locally (not committed; `output/video/` is git-ignored):

- `output/video/demo_captions.mp4`: captioned, **silent**. Recommended: record your own voice-over on top, reading the script below (QuickTime or iMovie: import the video, add a voice-over track).
- `output/video/demo_narrated.mp4`: the same video with a **draft narration in a synthetic macOS voice** (Samantha). If you submit this one, say in the submission that the voice is synthetic.
- `output/video/narration.txt`: the narration with the second each scene starts.

Recorded by `scripts/record_demo_video.py`, which drives the real app (live mode, hypothetical programs, synthetic company records) in a separate workspace on port 8002, so the class-demo database is untouched. The setup is in the script's docstring. To retake, restore `data/video_demo_prepared.db` to `data/video_demo.db` first. Each take makes two live model calls (classification and assistant), well under one US cent.

## Narration (timings from the current recording)

| Time | Screen | Say |
|---|---|---|
| 0:00 | Title card | Ocra Pipeline Tracker helps a small veterinary oncology team answer one question: can we fund our next milestone, and what could change that? All programs shown are hypothetical. |
| 0:11 | Overview | The Overview starts with our mission, All life matters, and eight plain-language questions, each answered in one line. |
| 0:18 | Pipelines, phase map | Pipelines shows where each program stands across twelve development phases, from discovery and patent filing to GLP safety, GCP field studies and approval. Each gate is a value-inflection point for a go / no-go decision. Gates pass in order, and passed gates leave a paw print. |
| 0:36 | New program, AI proposal | To add a program, describe it in plain words. The AI proposes a profile, marking each field stated, inferred or unknown, with its evidence. Nothing is saved until a person confirms. |
| 0:51 | Import review | Bank exports in three currencies go through review first. The app flags a duplicate, an ambiguous date, a formula-like cell, an internal transfer and a refund, and matches a payment to an open contract. |
| 1:05 | Budget and Runway | Net burn is now about USD 152K a month: a 7.2-month simple runway. The dated forecast falls below our reserve in February 2027. Each milestone shows actual spend to date against the estimate to complete. The AI never computes these numbers. |
| 1:22 | What-if scenario | Scenarios run on a copy. Delaying the pilot study three months moves the reserve breach to April, but leaves a funding gap of about USD 720K. |
| 1:32 | Competitors by pipeline | Competitors are listed by pipeline, with their product and latest public movement. |
| 1:37 | Regulatory | Official FDA and EMA guidance is labeled, quoted word for word, and mapped to milestones for a specialist to review. |
| 1:44 | AI Assistant | Managers can simply ask. The assistant answers through read-only tools, every figure is checked, and the trace shows the cost: a fraction of a cent. |
| 2:10 | 中文 toggle | The interface switches to Chinese in one click. |
| 2:16 | Agent runs and usage | Every AI run is measured. In testing, five prompt-injection attacks leaked no secrets and changed no records. |
| 2:24 | End card | Ocra Pipeline Tracker. All life matters. |

The assistant scene runs longer than its line (1:44–2:10) because the live model takes about 12 seconds to answer. In a voice-over, you can fill that pause with: "It found that the GLP safety study is funded, and listed what could change that."
