"""Drive the real app through the demonstration journey and save screenshots.

Prerequisites: the app is running on http://127.0.0.1:8000 (built frontend),
ideally in live mode on a class-demo database with synthetic records:

    cd backend
    APP_MODE=live DATABASE_PATH=data/class_demo.db ../.venv/bin/python -m app.demo.seed --into-current
    APP_MODE=live DATABASE_PATH=data/class_demo.db ENABLE_SCHEDULER=false ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

Then:  .venv/bin/python scripts/capture_journey.py
Uses the locally installed Google Chrome through Playwright (channel="chrome").
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "screenshots"
BASE = "http://127.0.0.1:8000"
LOG: list[str] = []


async def shot(page: Page, name: str, full: bool = False):
    await page.wait_for_timeout(700)
    path = OUT / f"{name}.png"
    await page.screenshot(path=str(path), full_page=full)
    LOG.append(name)
    print("saved", path.name, flush=True)


async def wait_job_text(page: Page, timeout_s: int = 240):
    """Wait until no visible 'running' status pill remains."""
    for _ in range(timeout_s * 2):
        running = await page.locator("text=• running").count() + await page.locator("text=• queued").count()
        if not running:
            return
        await page.wait_for_timeout(500)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        start = sys.argv[1] if len(sys.argv) > 1 else "all"  # "all" or "briefing" to resume

        if start == "all":
            await part_one(page)
        await part_two(page)
        (OUT / "journey_log.json").write_text(json.dumps({"screens": LOG, "browser_errors": errors[:50]}, indent=1))
        print("browser errors:", errors[:10] or "none")
        await browser.close()


async def part_one(page: Page):
    if True:
        # 0. overview (dismiss any daily briefing popup first)
        await page.goto(BASE + "/")
        await page.wait_for_timeout(1500)
        if await page.locator("text=Dismiss for today").count():
            await page.click("text=Dismiss for today")
        await shot(page, "01_overview_before")

        # 1-2. AI classification of a new description (proposal only: the workspace keeps its three pipelines)
        await page.goto(BASE + "/pipelines")
        await page.click("text=+ New program")
        await page.get_by_label("Internal identifier").fill("HX-401")
        await page.get_by_label("Program name").fill("Hypothetical Program Delta (proposal only)")
        await page.locator("textarea").first.fill("We are developing an oral small-molecule kinase inhibitor for canine mast cell tumors and initially considering the US and EU.")
        await page.click("text=Propose profile")
        await page.wait_for_selector("text=Regulatory caution", timeout=120000)
        await page.get_by_label("Indication").fill("mast cell tumor")
        await shot(page, "02_classification_proposal")
        await page.goto(BASE + "/pipelines")
        await page.wait_for_timeout(1200)
        await shot(page, "03_pipelines_three")

        # 3. budget line for an existing milestone that had none (HX-101 pivotal go / no-go)
        await page.goto(BASE + "/budget?program=1")
        await page.click("role=tab[name='Milestone budgets']")
        await page.click("text=+ Add budget line")
        await page.get_by_label("Milestone").select_option(label="HX-101: Pivotal field study go / no-go")
        await page.get_by_label("Planned amount").fill("60000")
        await page.get_by_label("Cash-out starts (month)").fill("2027-08")
        await page.get_by_label("Spread over months").fill("2")
        await page.get_by_label("Estimate source").fill("Synthetic CRO quote (class demo)")
        await page.click("text=Save as draft")
        await page.wait_for_timeout(800)
        await shot(page, "04_milestone_budgets", full=True)
        await page.goto(BASE + "/budget")
        await page.wait_for_timeout(800)

        # 4. import synthetic transactions through preview and confirm
        await page.click("role=tab[name='Import bank data']")
        await page.set_input_files("input[type=file]", str(ROOT / "sample_data" / "synthetic_ledger_multi_entity.xlsx"))
        await page.wait_for_selector("text=Worksheet")
        await page.get_by_label("Worksheet").select_option("Transactions")
        await page.wait_for_timeout(800)
        await page.click("text=Next: map columns")
        await page.click("button:has-text('Validate')")
        await page.wait_for_selector("text=Review rows")
        await shot(page, "05_import_review", full=True)
        await page.click("text=Next: reconciliation summary")
        await shot(page, "06_import_reconciliation", full=True)
        await page.click("button:has-text('Confirm and import')")
        await page.wait_for_selector("text=Imported")
        await shot(page, "07_import_committed")

        # 5. runway
        await page.click("role=tab[name='Summary']")
        await page.wait_for_timeout(1200)
        await shot(page, "08_budget_runway", full=True)

        # 6. milestone-delay scenario
        await page.click("role=tab[name='What-if scenarios']")
        await page.click("text=Pilot study starts 3 months later")
        await page.wait_for_selector("text=Baseline vs")
        await page.locator("select[aria-label='Choose milestone']").select_option(label="HX-101: Pilot field efficacy study")
        await page.wait_for_timeout(1200)
        await shot(page, "09_scenario_delay", full=True)

        # 7-8. live external research for HX-101
        await page.goto(BASE + "/pipelines/1")
        for button in ("Refresh competitor intelligence", "Refresh regulatory research", "Assess potential partners"):
            await page.click(f"text={button}")
            await page.wait_for_timeout(1500)
            await wait_job_text(page)
        await shot(page, "10_program_research_done")
        await page.goto(BASE + "/competitors")
        await page.wait_for_timeout(1500)
        await shot(page, "11_competitors_by_pipeline", full=True)
        await page.goto(BASE + "/competitors?program=1")
        await page.wait_for_timeout(800)
        await page.click("role=tab[name='All news']")
        await page.wait_for_timeout(1000)
        await shot(page, "11b_competitor_events", full=True)
        await page.click("role=tab[name='Follow-ups']")
        await shot(page, "12_action_queue")
        await page.goto(BASE + "/regulatory?program=1")
        await page.wait_for_timeout(1500)
        await shot(page, "13_regulatory_documents", full=True)
        await page.click("role=tab[name='Authorities and coverage']")
        await shot(page, "14_regulatory_coverage", full=True)



async def part_two(page: Page):
    if True:
        # briefing: generate, then the first visit of the day shows the popup
        await page.goto(BASE + "/briefing")
        if not await page.locator("text=Dismiss for today").count():
            await page.click("text=Refresh now")
            await page.wait_for_timeout(2000)
            await wait_job_text(page)
        await page.goto(BASE + "/")
        await page.wait_for_timeout(2000)
        if await page.locator("text=Dismiss for today").count():
            await shot(page, "15a_briefing_popup")
            await page.click("text=Dismiss for today")
        await page.goto(BASE + "/briefing")
        await page.wait_for_timeout(1500)
        await shot(page, "15_daily_briefing", full=True)
        await page.goto(BASE + "/markets?program=1")
        await page.click("text=Refresh market data")
        await page.wait_for_timeout(4000)
        await page.goto(BASE + "/markets?program=1")
        await page.wait_for_timeout(1500)
        await shot(page, "16_markets_partners", full=True)

        # 9-10. ask whether the next milestone is funded
        await page.goto(BASE + "/assistant")
        await page.get_by_label("Context program").select_option(label="HX-101")
        await page.fill("#q", "Is the next milestone for HX-101 funded? What could change that?")
        await page.click("button:has-text('Ask')")
        await page.wait_for_selector("text=Key figures", timeout=180000)
        await page.click("text=Execution trace")
        await shot(page, "17_assistant_answer", full=True)

        await page.goto(BASE + "/settings")
        await page.click("role=tab[name='Agent runs and usage']")
        await page.wait_for_timeout(1200)
        await shot(page, "18_agent_runs_usage", full=True)
        await page.goto(BASE + "/")
        await page.wait_for_timeout(1500)
        await shot(page, "19_overview_after", full=True)
        await page.goto(BASE + "/pipelines")
        await page.wait_for_timeout(1200)
        await shot(page, "20_pipelines_phase_map", full=True)
        # wide window so all twelve phase columns are visible at once (used in the report)
        await page.set_viewport_size({"width": 2000, "height": 1000})
        await page.goto(BASE + "/pipelines")
        await page.wait_for_timeout(1200)
        await page.locator(".card:has(.phase-grid)").screenshot(path=str(OUT / "20b_phase_map_wide.png"))
        LOG.append("20b_phase_map_wide")
        await page.set_viewport_size({"width": 1440, "height": 900})


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
