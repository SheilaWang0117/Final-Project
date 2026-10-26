"""Record the 2-3 minute demo video by driving the real app, with on-screen captions and a draft narration.

Writes to output/video/ (git-ignored):
  demo_captions.mp4   captioned, silent: record your own voice-over on top (recommended)
  demo_narrated.mp4   the same video with a draft narration from the macOS "say" voice
  narration.txt       the narration script with scene start times

Setup (uses a separate, freshly seeded workspace so the class-demo database is not touched):

    cd backend
    APP_MODE=live DATABASE_PATH=data/video_demo.db ../.venv/bin/python -m app.demo.seed --into-current
    APP_MODE=live DATABASE_PATH=data/video_demo.db ENABLE_SCHEDULER=false ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002

Then:
    .venv/bin/python scripts/record_demo_video.py --prepare   # runs competitor, regulatory and briefing research once
    cp data/video_demo.db data/video_demo_prepared.db          # recording commits an import; restore this copy before a retake
    FFMPEG=/path/to/ffmpeg .venv/bin/python scripts/record_demo_video.py

Needs Google Chrome (Playwright channel "chrome"), macOS `say`, and an ffmpeg binary (FFMPEG env var or on PATH).
Live mode makes two model calls during recording (classification, assistant), well under one US cent.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "video"
BASE = os.getenv("VIDEO_BASE", "http://127.0.0.1:8002")
VOICE, RATE = os.getenv("VIDEO_VOICE", "Samantha"), os.getenv("VIDEO_RATE", "186")
W, H = 1440, 900

# ---------------------------------------------------------------- overlay (captions, title cards, cursor)

INIT_JS = """
(() => {
  const css = `
  #demo-cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:1100px;z-index:99999;
    background:rgba(10,21,36,.88);color:#fff;font:500 21px/1.35 "Space Grotesk",system-ui,sans-serif;padding:12px 22px;
    border-radius:14px;border:1px solid rgba(45,226,196,.45);box-shadow:0 10px 30px rgba(0,0,0,.25);text-align:center;pointer-events:none}
  #demo-cap b{color:#7ff0dc}
  #demo-card{position:fixed;inset:0;z-index:100000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;
    background:radial-gradient(circle at 80% 15%,rgba(45,226,196,.35),transparent 45%),radial-gradient(circle at 10% 100%,rgba(232,160,74,.3),transparent 40%),
    linear-gradient(120deg,#0a1524,#123a4d 65%,#0d6d6b);color:#fff;font-family:"Space Grotesk",system-ui,sans-serif;text-align:center;pointer-events:none}
  #demo-card h1{font-size:64px;margin:0;letter-spacing:-.03em;background:none;color:#fff;-webkit-text-fill-color:#fff}
  #demo-card p{font-size:26px;margin:0;opacity:.92;max-width:1000px}
  #demo-card small{font-family:"JetBrains Mono",monospace;font-size:16px;color:#f6c48a;letter-spacing:.06em}
  #demo-cursor{position:fixed;width:22px;height:22px;margin:-4px 0 0 -4px;z-index:100001;pointer-events:none;transition:transform .08s}
  #demo-cursor.down{transform:scale(.8)}`;
  const boot = () => {
    if (!document.getElementById('demo-style')) {
      const s = document.createElement('style'); s.id = 'demo-style'; s.textContent = css; document.head.appendChild(s);
    }
    if (!document.getElementById('demo-cursor')) {
      const c = document.createElement('div'); c.id = 'demo-cursor';
      c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#0f2238" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.body.appendChild(c);
      const p = JSON.parse(sessionStorage.getItem('demoCursor') || '[720,450]');
      c.style.left = p[0] + 'px'; c.style.top = p[1] + 'px';
      document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
        sessionStorage.setItem('demoCursor', JSON.stringify([e.clientX, e.clientY])); }, true);
      document.addEventListener('mousedown', () => c.classList.add('down'), true);
      document.addEventListener('mouseup', () => c.classList.remove('down'), true);
    }
    window.__cap = (html) => {
      let d = document.getElementById('demo-cap');
      if (!html) { if (d) d.remove(); sessionStorage.removeItem('demoCap'); return; }
      if (!d) { d = document.createElement('div'); d.id = 'demo-cap'; document.body.appendChild(d); }
      d.innerHTML = html; sessionStorage.setItem('demoCap', html);
    };
    window.__card = (html) => {
      let d = document.getElementById('demo-card');
      if (!html) { if (d) d.remove(); return; }
      if (!d) { d = document.createElement('div'); d.id = 'demo-card'; document.body.appendChild(d); }
      d.innerHTML = html;
    };
    const saved = sessionStorage.getItem('demoCap');
    if (saved) window.__cap(saved);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
"""


async def cap(page: Page, html: str | None):
    await page.evaluate("h => window.__cap && window.__cap(h)", html)


async def goto(page: Page, path: str):
    await page.goto(BASE + path)
    await page.wait_for_timeout(900)


async def move_click(page: Page, locator, wait: int = 350):
    loc = locator.first if hasattr(locator, "first") else locator
    await loc.scroll_into_view_if_needed()
    box = await loc.bounding_box()
    if box:
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
        await page.wait_for_timeout(wait)
    await loc.click()


async def hover(page: Page, locator, wait: int = 600):
    loc = locator.first
    await loc.scroll_into_view_if_needed()
    box = await loc.bounding_box()
    if box:
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
    await page.wait_for_timeout(wait)


async def smooth_scroll(page: Page, y: int, ms: int = 1400, selector: str | None = None, x: int | None = None):
    await page.evaluate(
        """([y, ms, sel, x]) => new Promise(r => {
            const el = sel ? document.querySelector(sel) : document.scrollingElement;
            if (!el) return r();
            const sy = el.scrollTop, sx = el.scrollLeft, t0 = performance.now();
            const step = t => { const k = Math.min(1, (t - t0) / ms), e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k + 2, 2) / 2;
              if (y !== null) el.scrollTop = sy + (y - sy) * e; if (x !== null) el.scrollLeft = sx + (x - sx) * e;
              k < 1 ? requestAnimationFrame(step) : r(); };
            requestAnimationFrame(step); })""",
        [y, ms, selector, x],
    )


async def dismiss_popup(page: Page):
    if await page.locator("text=Dismiss for today").count():
        await move_click(page, page.locator("text=Dismiss for today"))
        await page.wait_for_timeout(500)


# ---------------------------------------------------------------- scenes


async def s_title(page: Page):
    await goto(page, "/")
    await page.evaluate("h => window.__card(h)", "<small>FINAL PROJECT · HYPOTHETICAL PROGRAMS · SYNTHETIC DATA</small><h1>Ocra Pipeline Tracker</h1>"
                        "<p>Can we fund the next scientific milestone, and what could change that?</p>")


async def s_overview(page: Page):
    await page.evaluate("() => window.__card(null)")
    await cap(page, "<b>Overview:</b> our mission, eight plain-language questions, today's briefing")
    await page.wait_for_timeout(2500)
    await dismiss_popup(page)
    await hover(page, page.locator(".ask-card").nth(0), 900)
    await hover(page, page.locator(".ask-card").nth(1), 900)
    await smooth_scroll(page, 560, 1600)


async def s_phase_map(page: Page):
    await goto(page, "/pipelines")
    await cap(page, "<b>Phase map:</b> pipelines × 12 development phases · gates = value-inflection decisions")
    await smooth_scroll(page, 520, 1400)
    await hover(page, page.locator(".ph-paw"), 1000)
    await hover(page, page.locator(".ph-gate.next"), 1000)
    await smooth_scroll(page, None, 2200, ".phase-scroll", 600)
    await smooth_scroll(page, None, 1200, ".phase-scroll", 0)


async def s_classify(page: Page):
    await cap(page, "<b>New program:</b> the AI proposes a profile; a person reviews and confirms")
    await smooth_scroll(page, 0, 800)
    await move_click(page, page.locator("text=+ New program"))
    await page.get_by_label("Internal identifier").fill("HX-401")
    await page.get_by_label("Program name").fill("Hypothetical Program Delta (proposal only)")
    await page.locator("textarea").first.click()
    await page.locator("textarea").first.type("We are developing an oral small-molecule kinase inhibitor for canine mast cell tumors and initially considering the US and EU.", delay=12)
    await move_click(page, page.locator("text=Propose profile"))
    await page.wait_for_selector("text=Regulatory caution", timeout=120000)
    await page.wait_for_timeout(800)
    await smooth_scroll(page, 380, 1800, ".modal")
    await page.wait_for_timeout(1500)


async def s_import(page: Page):
    await page.keyboard.press("Escape")
    await goto(page, "/budget")
    await cap(page, "<b>Import:</b> bank exports in HKD, CNY and USD are checked row by row before anything is saved")
    await move_click(page, page.locator("role=tab[name='Import bank data']"))
    await page.set_input_files("input[type=file]", str(ROOT / "sample_data" / "synthetic_ledger_multi_entity.xlsx"))
    await page.wait_for_selector("text=Worksheet")
    await page.get_by_label("Worksheet").select_option("Transactions")
    await page.wait_for_timeout(700)
    await move_click(page, page.locator("text=Next: map columns"))
    await move_click(page, page.locator("button:has-text('Validate')"))
    await page.wait_for_selector("text=Review rows")
    await smooth_scroll(page, 1050, 1800)
    await page.wait_for_timeout(5200)
    await move_click(page, page.locator("text=Next: reconciliation summary"))
    await page.wait_for_timeout(1200)
    await move_click(page, page.locator("button:has-text('Confirm and import')"))
    await page.wait_for_selector("text=Imported")


async def s_runway(page: Page):
    await cap(page, "<b>Runway:</b> deterministic cash, burn and forecast · actual spend to date vs estimate to complete")
    await move_click(page, page.locator("role=tab[name='Summary']"))
    await page.wait_for_timeout(1500)
    await smooth_scroll(page, 0, 600)
    await hover(page, page.locator(".stat").nth(3), 1800)
    await smooth_scroll(page, 980, 2200)
    await page.wait_for_timeout(1500)


async def s_scenario(page: Page):
    await cap(page, "<b>What-if:</b> scenarios run on a copy; the approved plan never changes")
    await smooth_scroll(page, 0, 700)
    await move_click(page, page.locator("role=tab[name='What-if scenarios']"))
    await move_click(page, page.locator("text=Pilot study starts 3 months later"))
    await page.wait_for_selector("text=Baseline vs")
    await page.locator("select[aria-label='Choose milestone']").select_option(label="HX-101: Pilot field efficacy study")
    await page.wait_for_timeout(800)
    await smooth_scroll(page, 700, 1800)


async def s_competitors(page: Page):
    await goto(page, "/competitors")
    await cap(page, "<b>Competitors by pipeline:</b> who, which product, latest movement, with sources and dates")
    await hover(page, page.locator(".comp-row").nth(0), 1500)
    await smooth_scroll(page, 300, 1500)


async def s_regulatory(page: Page):
    await goto(page, "/regulatory?program=1")
    await cap(page, "<b>Regulatory:</b> official FDA and EMA guidance, status, verbatim passages, milestones flagged for review")
    await smooth_scroll(page, 420, 2200)
    await page.wait_for_timeout(1200)
    await smooth_scroll(page, 900, 2000)


async def s_assistant(page: Page):
    await goto(page, "/assistant")
    await cap(page, "<b>Ask:</b> answers come from read-only tools; every figure is checked")
    await page.get_by_label("Context program").select_option(label="HX-101")
    await page.locator("#q").click()
    await page.locator("#q").type("Is the next milestone for HX-101 funded? What could change that?", delay=18)
    await move_click(page, page.locator("button:has-text('Ask')"))
    await page.wait_for_selector("text=Key figures", timeout=180000)
    await page.wait_for_timeout(800)
    await smooth_scroll(page, 430, 1800)
    await page.wait_for_timeout(1500)
    await move_click(page, page.locator("text=Execution trace"))
    await smooth_scroll(page, 900, 1600)


async def s_chinese(page: Page):
    await goto(page, "/")
    await cap(page, "<b>中文 / EN:</b> the whole interface switches language in one click")
    await move_click(page, page.locator(".crumbs .lang-toggle button:has-text('中文')"))
    await page.wait_for_timeout(2600)
    await move_click(page, page.locator(".crumbs .lang-toggle button:has-text('EN')"))
    await page.wait_for_timeout(600)


async def s_safety(page: Page):
    await goto(page, "/settings")
    await cap(page, "<b>Cost and safety:</b> every AI run is measured; retrieved pages are treated as untrusted")
    await move_click(page, page.locator("role=tab[name='Agent runs and usage']"))
    await page.wait_for_timeout(1000)
    await smooth_scroll(page, 300, 1500)


async def s_end(page: Page):
    await cap(page, None)
    await page.evaluate("h => window.__card(h)", "<small>OCRA BIOTECHNOLOGY · FINAL PROJECT</small><h1>All life matters</h1>"
                        "<p>Ocra Pipeline Tracker: our science, our money and the outside world, in one place.</p>")


SCENES = [
    ("title", s_title, "Ocra Pipeline Tracker helps a small veterinary oncology team answer one question: can we fund our next milestone, and what could change that? "
                       "All programs shown are hypothetical."),
    ("overview", s_overview, "The Overview starts with our mission, All life matters, and eight plain-language questions, each answered in one line."),
    ("phase map", s_phase_map, "Pipelines shows where each program stands across twelve development phases, from discovery and patent filing to G L P safety, "
                               "G C P field studies, and approval. Each gate is a value inflection point for a go or no-go decision. "
                               "Gates pass in order, and passed gates leave a paw print."),
    ("classification", s_classify, "To add a program, describe it in plain words. The AI proposes a profile, marking each field stated, inferred, or unknown, with its evidence. "
                                   "Nothing is saved until a person confirms."),
    ("import", s_import, "Bank exports in three currencies go through review first. The app flags a duplicate, an ambiguous date, a formula-like cell, "
                         "an internal transfer, and a refund, and matches a payment to an open contract."),
    ("runway", s_runway, "Net burn is now about one hundred fifty-two thousand dollars a month: a seven point two month simple runway. "
                         "The dated forecast falls below our reserve in February twenty twenty-seven. "
                         "Each milestone shows actual spend to date against the estimate to complete. The AI never computes these numbers."),
    ("scenario", s_scenario, "Scenarios run on a copy. Delaying the pilot study three months moves the reserve breach to April, "
                             "but leaves a funding gap of about seven hundred twenty thousand dollars."),
    ("competitors", s_competitors, "Competitors are listed by pipeline, with their product and latest public movement."),
    ("regulatory", s_regulatory, "Official F D A and E M A guidance is labeled, quoted word for word, and mapped to milestones for a specialist to review."),
    ("assistant", s_assistant, "Managers can simply ask. The assistant answers through read-only tools, every figure is checked, "
                               "and the trace shows the cost: a fraction of a cent."),
    ("chinese", s_chinese, "The interface switches to Chinese in one click."),
    ("safety", s_safety, "Every AI run is measured. In testing, five prompt injection attacks leaked no secrets, and changed no records."),
    ("end", s_end, "Ocra Pipeline Tracker. All life matters."),
]

# ---------------------------------------------------------------- audio helpers


def ffmpeg() -> str:
    exe = os.getenv("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg not found: set FFMPEG=/path/to/ffmpeg")
    return exe


def audio_seconds(path: Path) -> float:
    out = subprocess.run(["afinfo", str(path)], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "estimated duration" in line:
            return float(line.split(":")[1].split()[0])
    return 0.0


def make_narration() -> list[tuple[Path, float]]:
    clips = []
    for i, (name, _, text) in enumerate(SCENES):
        path = OUT / f"n{i:02d}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(path), text], check=True)
        clips.append((path, audio_seconds(path)))
    return clips


# ---------------------------------------------------------------- prepare / record


def api(method: str, path: str, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"null")


def prepare():
    """Run the research once so the evidence pages have content (live: a few tenths of a US cent)."""
    jobs = [api("POST", "/api/programs/1/research/competitors"), api("POST", "/api/programs/1/research/regulatory"), api("POST", "/api/briefing/refresh")]
    for j in jobs:
        jid = j.get("job_id")
        for _ in range(240):
            st = api("GET", f"/api/jobs/{jid}")
            if st["status"] not in ("queued", "running"):
                print("job", jid, st["status"], flush=True)
                break
            time.sleep(1)


async def record():
    OUT.mkdir(parents=True, exist_ok=True)
    clips = make_narration()
    raw = OUT / "raw"
    shutil.rmtree(raw, ignore_errors=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        ctx = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(raw), record_video_size={"width": W, "height": H})
        await ctx.add_init_script(INIT_JS)
        page = await ctx.new_page()
        t0 = time.monotonic()
        starts = []
        for (name, fn, _), (_, dur) in zip(SCENES, clips):
            start = time.monotonic() - t0
            starts.append(start)
            await fn(page)
            left = dur + 0.7 - (time.monotonic() - t0 - start)
            if left > 0:
                await page.wait_for_timeout(int(left * 1000))
            print(f"{start:6.1f}s  {name}", flush=True)
        await page.wait_for_timeout(1500)
        video = await page.video.path()
        await ctx.close()
        await browser.close()
    total = time.monotonic() - t0
    fx = ffmpeg()
    silent = OUT / "demo_captions.mp4"
    subprocess.run([fx, "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium", "-movflags", "+faststart", str(silent)], check=True)
    # narration: each clip delayed to its scene start, mixed into one track and padded to the video's length
    probe = subprocess.run([fx, "-i", str(silent)], capture_output=True, text=True).stderr
    hh, mm, ss = probe.split("Duration: ", 1)[1].split(",", 1)[0].split(":")
    vdur = int(hh) * 3600 + int(mm) * 60 + float(ss)
    args = [fx, "-y", "-loglevel", "error", "-i", str(silent)]
    for path, _ in clips:
        args += ["-i", str(path)]
    filt = "".join(f"[{i + 1}:a]adelay={int(s * 1000)}|{int(s * 1000)}[a{i}];" for i, s in enumerate(starts))
    filt += "".join(f"[a{i}]" for i in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0,apad=whole_dur={vdur:.2f}[aout]"
    narrated = OUT / "demo_narrated.mp4"
    subprocess.run(args + ["-filter_complex", filt, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{vdur:.2f}", str(narrated)], check=True)
    lines = [f"[{int(s // 60)}:{int(s % 60):02d}] {name.upper()}\n{text}\n" for s, (name, _, text) in zip(starts, SCENES)]
    (OUT / "narration.txt").write_text(f"Total length about {int(total // 60)}:{int(total % 60):02d}\n\n" + "\n".join(lines))
    for path, _ in clips:
        path.unlink()
    shutil.rmtree(raw, ignore_errors=True)
    print("wrote", silent.name, narrated.name, "narration.txt", f"({total:.0f}s)")


if __name__ == "__main__":
    if "--prepare" in sys.argv:
        prepare()
    else:
        asyncio.run(record())
