"""Demo-mode Planning Assistant: deterministic templates over the same tools.

Used only when APP_MODE=demo (no API key needed). Answers are labeled as
template answers and never presented as model output. English and Simplified
Chinese templates; figures always come from the tools unchanged.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from . import tools as T


async def template_answer(question: str, deps, language: str = "en") -> dict:
    ctx = SimpleNamespace(deps=deps)
    zh = language == "zh"

    def L(en: str, cn: str) -> str:
        return cn if zh else en

    q = question.lower()
    figures, sources, assumptions, gaps, actions = [], [], [], [], []

    async def call(fn, **kw):
        res = await fn(ctx, **kw)
        deps.extra.setdefault("tool_results", []).append(res)
        return res

    pipe = await call(T.get_pipeline, program_id=deps.program_id)
    progs = pipe["programs"]
    if any(w in q for w in ("delay", "later", "slip", "postpone", "推迟", "延迟", "延期")):
        months = int(m.group(1)) if (m := re.search(r"(\d+)\s*(month|个月)", q)) else 3
        target = next((p["next_milestone"] for p in progs if p["next_milestone"]), None)
        if not target:
            answer = L("There is no open milestone to delay.", "目前没有可推迟的未完成里程碑。")
        else:
            sim = await call(T.simulate_milestone_delay, milestone_id=target["id"], months=months)
            base_m = sim["below_reserve_month"]["base"] or L("beyond the horizon", "预测期之外")
            scen_m = sim["below_reserve_month"]["scenario"] or L("beyond the horizon", "预测期之外")
            answer = L(
                f"If '{sim['milestone']}' starts {months} months later, the month cash falls below the reserve moves from {base_m} to {scen_m}. "
                f"Lowest projected cash: {sim['lowest_cash']['base']} (baseline) vs {sim['lowest_cash']['scenario']} (delayed). The approved plan is unchanged.",
                f"如果“{sim['milestone']}”推迟 {months} 个月开始，现金低于最低储备的月份将从 {base_m} 变为 {scen_m}。"
                f"预测最低现金：基线 {sim['lowest_cash']['base']}，推迟后 {sim['lowest_cash']['scenario']}。已批准的计划不会被修改。")
            figures += [{"label": L("Lowest cash, baseline", "最低现金（基线）"), "value": sim["lowest_cash"]["base"], "tool": "simulate_milestone_delay"},
                        {"label": L("Lowest cash, delayed", "最低现金（推迟后）"), "value": sim["lowest_cash"]["scenario"], "tool": "simulate_milestone_delay"}]
            assumptions.append(L(sim["note"], "依赖该里程碑的后续里程碑同步推迟；相关承付款随之移动。基于副本计算。"))
    elif any(w in q for w in ("over budget", "overrun", "most over", "超支", "超预算")):
        b = await call(T.get_budget_summary)
        rows = [r for r in b["by_program"] if r["forecast_vs_approved_pct"] != "n/a"]
        if rows:
            worst = max(rows, key=lambda r: float(r["forecast_vs_approved_pct"].rstrip("%")))
            answer = L(f"{worst['program']} has the largest forecast overrun versus its approved budget: {worst['forecast_minus_approved']} ({worst['forecast_vs_approved_pct']}).",
                       f"{worst['program']} 相对已批准预算的预测超支最大：{worst['forecast_minus_approved']}（{worst['forecast_vs_approved_pct']}）。")
            figures.append({"label": L(f"{worst['program']} forecast minus approved", f"{worst['program']} 预测减已批准"), "value": worst["forecast_minus_approved"], "tool": "get_budget_summary"})
        else:
            answer = L("No program has an approved budget to compare against yet.", "目前还没有可比较的已批准预算。")
        assumptions.append(L(b["definition"], "剩余预测 = 已批准（未批准时用计划）金额 + 应急费用 − 已付实际 − 未付承付款；承付款与已付实际分开计算。"))
    elif any(w in q for w in ("competitor", "changed", "this week", "竞争", "对手", "本周")):
        ev = await call(T.get_competitor_events, program_id=deps.program_id, days=7 if ("week" in q or "本周" in q) else 30)
        if ev["events"]:
            answer = L("Captured competitor/field events:\n", "已捕获的竞争/领域动态：\n") + "\n".join(
                f"- {e['title']} ({e['source']}, {e['published'] or L('date n/a', '日期不详')})" for e in ev["events"][:6])
            sources += [{"title": e["title"], "url": e["url"]} for e in ev["events"][:6]]
        else:
            answer = L("No competitor events were captured in that period.", "该期间未捕获到竞争对手动态。")
        gaps.append(L(ev["note"], "仅包含本应用检索到的事件，并非竞争对手活动的完整记录。"))
    elif any(w in q for w in ("regulat", "guidance", "fda", "ema", "mara", "法规", "监管", "指南")):
        rd = await call(T.get_regulatory_documents, program_id=deps.program_id)
        if rd["documents"]:
            answer = L("Regulatory documents flagged as possibly relevant (research summaries, not determinations):\n",
                       "可能相关的法规文件（研究摘要，并非监管结论）：\n") + "\n".join(
                f"- {d['title']} ({d['authority']}, {d['status']}, {d['binding']})" for d in rd["documents"][:6])
            sources += [{"title": d["title"], "url": d["url"]} for d in rd["documents"][:6]]
        else:
            answer = L("No regulatory documents have been assessed yet. Run a regulatory refresh for a confirmed program.", "尚未评估任何法规文件。请对已确认的项目运行法规研究。")
        gaps.append(L(rd["note"], "研究摘要并非监管结论；覆盖范围仅限已检索的官方来源。"))
    elif any(w in q for w in ("partner", "licens", "合作", "授权", "伙伴")):
        pc = await call(T.list_partner_candidates, program_id=deps.program_id)
        if pc["partners"]:
            answer = L("Potential partners by documented fit (not confirmed interest):\n", "按已记录证据排序的潜在合作伙伴（并非已确认的合作意向）：\n") + "\n".join(
                f"- {p['company']}: {L('fit score', '匹配分')} {p['fit_score']}" for p in pc["partners"][:5])
        else:
            answer = L("No partner assessment has been run yet.", "尚未进行合作伙伴评估。")
        gaps.append(L(pc["note"], "基于公开证据的潜在合作伙伴，并非已确认的合作意向。"))
    else:
        target = next((p["next_milestone"] for p in progs if p["next_milestone"]), None)
        fc = await call(T.calculate_cash_forecast)
        if target:
            f = await call(T.check_milestone_funding, milestone_id=target["id"])
            verdict = (L("funded", "资金充足") if f["funded"] else L("not fully funded", "资金不足") if f["funded"] is False else L("cannot be confirmed", "无法确认"))
            answer = L(
                f"The next milestone, '{f['milestone']}' (planned end {f['planned_end']}), is {verdict} under the current plan. "
                f"Direct cost to reach it: {f['direct_cost_to_reach']}. Lowest projected cash through that date: {f['lowest_projected_cash_through_milestone']} "
                f"against a minimum reserve of {f['minimum_reserve']}" + (f"; funding gap {f['funding_gap']}." if f["funded"] is False else "."),
                f"下一个里程碑“{f['milestone']}”（计划完成 {f['planned_end']}）在当前计划下{verdict}。"
                f"达成所需直接成本：{f['direct_cost_to_reach']}。截至该日期的预测最低现金：{f['lowest_projected_cash_through_milestone']}，"
                f"最低储备为 {f['minimum_reserve']}" + (f"；资金缺口 {f['funding_gap']}。" if f["funded"] is False else "。"))
            figures += [{"label": L("Direct cost to reach", "达成所需直接成本"), "value": f["direct_cost_to_reach"], "tool": "check_milestone_funding"},
                        {"label": L("Available cash", "可用现金"), "value": fc["available_cash"], "tool": "calculate_cash_forecast"},
                        {"label": L("Net burn / month", "月净消耗"), "value": fc["net_burn_per_month"], "tool": "calculate_cash_forecast"}]
            gaps += f["data_gaps"]
            assumptions.append(L(f["definition"], "资金充足 = 在里程碑计划完成月之前，预测的月末现金（含所有项目、承付款和已确认资金流）始终不低于最低储备。"))
        else:
            answer = L(f"Available cash is {fc['available_cash']}; cash falls below the reserve in {fc['forecast']['month_cash_falls_below_reserve']}.",
                       f"可用现金为 {fc['available_cash']}；现金将在 {fc['forecast']['month_cash_falls_below_reserve']} 低于最低储备。")
        gaps += fc["data_warnings"][:4]
    return {"answer": answer, "key_figures": figures, "sources": sources, "assumptions": assumptions, "gaps": gaps,
            "suggested_actions": actions, "grounding": {"unverified_figures": [], "removed_sources": []}}
