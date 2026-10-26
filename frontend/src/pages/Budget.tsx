import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type Json } from "../api";
import { BurnChart, CashForecastChart, ChartMeta, Legend, SERIES } from "../components/charts";
import { Badge, Empty, ErrorBox, Loading, PageHead, Prov, Stat, StatusPill, Tabs, useApi } from "../components/ui";
import { dateOnly, money } from "../format";
import { useI18n } from "../i18n";
import ImportWizard from "./ImportWizard";

const DEF_ZH: Record<string, string> = {
  gross_burn: "所选期间的运营现金流出 ÷ 月数。",
  net_burn: "所选期间的运营现金流出减运营现金流入（含退款）÷ 月数。不含融资流入和公司内部账户间转账。",
  simple_runway: "已对账可用现金 ÷ 月平均净消耗（仅当净消耗为正）。",
  forecast_runway: "根据未来预算计划、未付承付款和已确认资金流，预测月末现金首次低于最低储备（以及低于零）的月份。",
  available_cash: "各账户最近一次已对账余额，加上之后的交易。仅导入交易不会形成余额。",
  scope: "基于您录入的法律实体的管理现金视图，并非经审计或法定合并财务报表。",
};
const ZH_METHOD = "从已对账可用现金出发，每月扣除预算剩余成本（按月度计划或平均分摊至里程碑结束）、到期的未付承付款和已确认的计划资金流。假设性流入只在情景中计入。未来金额按截止日汇率换算，不模拟汇率变动。";
const ZH_FX = "每笔金额按交易日（或预测截止日）当天或之前最近记录的汇率单独换算；同日手动汇率优先；欧洲央行参考汇率通过欧元交叉换算；四舍五入到报告币种最小单位。缺少汇率的金额不计入合计并单独列出，绝不未经换算直接相加。";

export default function Budget() {
  const { t } = useI18n();
  const [sp] = useSearchParams();
  const [tab, setTab] = useState("summary");
  const [burnMonths, setBurnMonths] = useState<number | null>(null);
  const sum = useApi(`/api/finance/summary${burnMonths ? `?burn_months=${burnMonths}` : ""}`);
  const reloadAll = () => sum.reload();
  return (
    <div>
      <PageHead title={t("Budget and Runway")} question={t("How much cash do we have, how long will it last, and can we afford the next milestone?")}
        next={[["/pipelines", t("Pipelines")], ["/assistant", t("AI Assistant")]]}>
        <a className="btn" href="/api/finance/export/summary.csv">{t("Export summary + assumptions (CSV)")}</a>
        <a className="btn" href="/api/finance/export/transactions.csv">{t("Export transactions (CSV)")}</a>
      </PageHead>
      <div className="tiny muted" style={{ marginTop: -10, marginBottom: 10 }}>{t("Deterministic calculations (decimal minor units, explicit rounding). The AI never computes these numbers. Management view — not audited or statutory consolidated statements.")}</div>
      <Tabs value={tab} onChange={setTab} tabs={[
        ["summary", t("Summary"), t("Start here: cash, burn, runway, and spending by pipeline and milestone.")],
        ["scenarios", t("What-if scenarios"), t("Test a delay, a cost change or new financing without touching the approved plan.")],
        ["budgets", t("Milestone budgets"), t("Plan and approve the cost of each milestone.")],
        ["import", t("Import bank data"), t("Upload a CSV/XLSX bank or ledger export, review it, then confirm.")],
        ["transactions", t("Transactions"), t("Check and correct how each payment is allocated.")],
        ["commitments", t("Commitments and flows"), t("Contracts not yet paid, expected grants or financing, shared-cost rules.")],
        ["cash", t("Cash, FX and settings"), t("Bank balances, exchange rates, reserve and reporting currency.")],
      ]} />
      {tab === "summary" && <Summary sum={sum} burnMonths={burnMonths} setBurnMonths={setBurnMonths} />}
      {tab === "budgets" && <Budgets programFilter={sp.get("program")} onChange={reloadAll} />}
      {tab === "transactions" && <Transactions onChange={reloadAll} />}
      {tab === "import" && <ImportWizard onCommitted={reloadAll} />}
      {tab === "cash" && <CashFx onChange={reloadAll} />}
      {tab === "commitments" && <Commitments onChange={reloadAll} />}
      {tab === "scenarios" && <Scenarios />}
    </div>
  );
}

// ------------------------------------------------------------------ summary

function Summary({ sum, burnMonths, setBurnMonths }: { sum: Json; burnMonths: number | null; setBurnMonths: (n: number) => void }) {
  const { t, tl, lang } = useI18n();
  if (sum.error) return <ErrorBox error={sum.error} onRetry={sum.reload} />;
  if (!sum.data) return <Loading />;
  const s = sum.data;
  const ccy = s.currency;
  const fc = s.forecast;
  const zh = lang === "zh";
  const def = (k: string) => (zh && DEF_ZH[k]) || s.definitions[k];
  return (
    <div>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat k={t("Available cash")} v={s.cash.complete ? money(s.cash.available_cash_minor, ccy, { compact: true }) : t("Incomplete")} d={t("as of {d}", { d: s.as_of })} title={def("available_cash")} />
        <Stat k={t("Gross burn / month")} v={money(s.burn.gross_burn_monthly_minor, ccy, { compact: true })} d={t("{d} + {n} months", { d: s.burn.period_start, n: s.burn.months })} title={def("gross_burn")} />
        <Stat k={t("Net burn / month")} v={money(s.burn.net_burn_monthly_minor, ccy, { compact: true })} d={t("Simple runway: {r}", { r: s.simple_runway.months ? t("{n} months", { n: s.simple_runway.months }) : tl(s.simple_runway.status) })} title={def("net_burn")} />
        <Stat k={t("Forecast runway")} v={fc.below_reserve_month || (fc.start_cash_minor == null ? t("Incomplete") : t("Beyond horizon"))} d={t("below reserve · below zero: {m}", { m: fc.cash_out_month || t("not in horizon") })} title={def("forecast_runway")} />
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-head">
            <h2>{t("Monthly operating cash flows")}</h2>
            <label className="f small">{t("Burn period")}
              <select value={burnMonths || s.settings.burn_period_months} onChange={(e) => setBurnMonths(Number(e.target.value))}>{[1, 3, 6, 12].map((m) => <option key={m} value={m}>{t("last {n} full months", { n: m })}</option>)}</select>
            </label>
          </div>
          <BurnChart series={s.burn.series} ccy={ccy} />
          <ChartMeta rows={[[t("Period"), t("{a} to {b} (exclusive)", { a: s.burn.period_start, b: s.burn.period_end_exclusive })], [t("Excluded"), t("Financing inflows {f} · {n} transfer(s)", { f: money(s.burn.excluded.financing_in, ccy), n: s.burn.excluded.transfers })], [t("Scope"), zh ? "所有法律实体（管理视图，非法定合并）" : s.burn.scope], [t("Currency"), t("{c} (converted per transaction date)", { c: ccy })]]} />
          {s.burn.intercompany.pairs.length > 0 && <div className="small muted" style={{ marginTop: 6 }}>{t("Matched intercompany transfers:")} {s.burn.intercompany.pairs.map((p: Json) => `${p.from_entity || "?"} → ${p.to_entity || "?"}`).join("; ")} {t("(excluded from burn and income).")}</div>}
        </div>
        <div className="card">
          <h2>{t("Cash forecast")}</h2>
          {fc.start_cash_minor == null ? <Empty title={t("Cash balance incomplete")}>{t("Add reconciled balances for every active account (Cash, FX and settings).")}</Empty> : <CashForecastChart months={fc.months} reserve={fc.reserve_minor} ccy={ccy} />}
          <ChartMeta rows={[[t("Start"), t("{c} on {d}", { c: money(fc.start_cash_minor, ccy), d: fc.as_of })], [t("Reserve"), money(fc.reserve_minor, ccy)], [t("Method"), zh ? ZH_METHOD : fc.method]]} />
        </div>
      </div>
      <PipelineSpend pipelines={s.pipelines} shared={s.budget_by_program.find((p: Json) => !p.program_id)} ccy={ccy} />
      <div className="grid g2">
        <div className="card">
          <h2>{t("Upcoming commitments")}</h2>
          {s.commitments_upcoming.length === 0 ? <Empty title={t("No open commitments")} /> : (
            <table className="t"><tbody>{s.commitments_upcoming.map((c: Json) => <tr key={c.id}><td>{dateOnly(c.expected_payment_date)}</td><td>{c.counterparty}<div className="tiny muted">{c.program_code} · {c.description}</div></td><td className="n">{money(c.amount_minor, c.currency)}</td></tr>)}</tbody></table>
          )}
        </div>
        <div className="card">
          <h2>{t("Definitions")}</h2>
          <dl className="kv small">{Object.keys(s.definitions).map((k) => <div key={k} style={{ display: "contents" }}><dt>{tl(k)}</dt><dd>{def(k)}</dd></div>)}</dl>
          <div className="tiny muted" style={{ marginTop: 6 }}>{t("FX:")} {zh ? ZH_FX : s.fx_method}</div>
        </div>
      </div>
    </div>
  );
}

function PipelineSpend({ pipelines, shared, ccy }: { pipelines: Json[]; shared: Json; ccy: string }) {
  const { t, tl } = useI18n();
  const max = Math.max(1, ...pipelines.flatMap((p) => p.milestones.map((m: Json) => m.total_minor)));
  const name = (m: Json) => (m.milestone_id ? m.milestone : t("Other program costs (not tied to a milestone)"));
  return (
    <div className="card">
      <div className="card-head">
        <h2>{t("Actual spend to date vs. estimate to complete, by pipeline and milestone")}</h2>
        <Legend items={[[t("Actual spend to date"), SERIES[0]], [t("Estimate to complete (open commitments + remaining budget)"), SERIES[2]]]} />
      </div>
      {pipelines.length === 0 && <Empty title={t("No pipelines yet")}>{t("Add a program in Pipelines.")}</Empty>}
      <div className="grid g3">
        {pipelines.map((p) => (
          <section key={p.program_id} className="pipe-spend">
            <div className="pipe-spend-head">
              <b>{p.code}</b> <span className="small muted">{p.name}</span> {p.status !== "active" && <Badge>{tl(p.status)}</Badge>}
              <div className="small">{t("Actual to date {a} · Estimate to complete {b}", { a: money(p.spent_minor, ccy, { compact: true }), b: money(p.to_spend_minor, ccy, { compact: true }) })}</div>
            </div>
            {p.milestones.length === 0 && <div className="small muted">{t("No milestones yet.")}</div>}
            {p.milestones.map((m: Json) => (
              <div key={m.milestone_id ?? "other"} className="ms-spend">
                <div className="ms-spend-name">
                  <span>{name(m)}</span>
                  {m.status && <span className="tiny muted">{tl(m.status)}{m.planned_end ? ` · ${t("ends {d}", { d: dateOnly(m.planned_end) })}` : ""}</span>}
                </div>
                {m.budgeted ? (
                  <>
                    <div className="spend-bar" role="img" aria-label={`${name(m)}: ${t("Actual spend to date")} ${money(m.spent_minor, ccy)}, ${t("Estimate to complete")} ${money(m.to_spend_minor, ccy)}`}>
                      {m.spent_minor > 0 && <i style={{ width: `${(m.spent_minor / max) * 100}%`, background: SERIES[0] }} title={`${t("Actual spend to date")}: ${money(m.spent_minor, ccy)}`} />}
                      {m.to_spend_minor > 0 && <i style={{ width: `${(m.to_spend_minor / max) * 100}%`, background: SERIES[2] }} title={`${t("Estimate to complete")}: ${money(m.to_spend_minor, ccy)}${m.committed_minor ? ` (${t("of which contractually committed")} ${money(m.committed_minor, ccy)})` : ""}`} />}
                    </div>
                    <div className="tiny ms-spend-nums"><span>{t("Actual to date")} <b>{money(m.spent_minor, ccy, { compact: true })}</b></span><span>{t("Estimate to complete")} <b>{money(m.to_spend_minor, ccy, { compact: true })}</b></span>{m.budget_minor != null && <span className="muted">{m.approved ? t("approved budget {b}", { b: money(m.budget_minor, ccy, { compact: true }) }) : t("draft budget {b}", { b: money(m.budget_minor, ccy, { compact: true }) })}</span>}</div>
                  </>
                ) : m.status === "done" ? (
                  <div className="tiny muted">{t("Completed · no costs recorded against this milestone")}</div>
                ) : (
                  <div className="tiny muted">{t("No budget yet — add one in Milestone budgets.")}</div>
                )}
              </div>
            ))}
          </section>
        ))}
      </div>
      {shared && <div className="tiny muted" style={{ marginTop: 10 }}>{t("Company running costs (payroll, rent, overhead) belong to no single pipeline and are not shown above: actual to date {a}, estimate to complete {b}.", { a: money(shared.actual_minor, ccy, { compact: true }), b: money(shared.open_commitments_minor + shared.remaining_forecast_minor, ccy, { compact: true }) })}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ budgets

function Budgets({ programFilter, onChange }: { programFilter: string | null; onChange: () => void }) {
  const { t } = useI18n();
  const lines = useApi(`/api/finance/budget-lines${programFilter ? `?program_id=${programFilter}` : ""}`);
  const progs = useApi("/api/programs");
  const ref = useApi("/api/reference");
  const tlData = useApi("/api/timeline");
  const [form, setForm] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const empty = { program_id: programFilter || "", milestone_id: "", category: "CRO services", description: "", currency: "USD", planned: "", contingency_pct: "10", owner: "", estimate_source: "", assumptions: "", start: "", months: "3" };
  const save = async () => {
    setErr(null);
    try {
      const months = Math.max(1, Number(form.months) || 1);
      const total = Number(String(form.planned).replace(/,/g, ""));
      const schedule: Record<string, string> = {};
      if (form.start) {
        const [y, m] = form.start.split("-").map(Number);
        const per = Math.floor((total * 100) / months);
        for (let i = 0; i < months; i++) {
          const d = new Date(y, m - 1 + i, 1);
          const cents = i === months - 1 ? Math.round(total * 100) - per * (months - 1) : per;
          schedule[`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`] = (cents / 100).toFixed(2);
        }
      }
      const body = { program_id: form.program_id ? Number(form.program_id) : null, milestone_id: form.milestone_id ? Number(form.milestone_id) : null, category: form.category, description: form.description || null,
        currency: form.currency, planned: total.toFixed(2), contingency_pct: form.contingency_pct || "0", owner: form.owner || null, estimate_source: form.estimate_source || null, assumptions: form.assumptions || null, schedule };
      if (form.id) await api.put(`/api/finance/budget-lines/${form.id}`, body);
      else await api.post("/api/finance/budget-lines", body);
      setForm(null);
      lines.reload();
      onChange();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const approve = async (l: Json) => {
    const v = window.prompt(t("Approve amount ({c}). This is logged as a budget approval.", { c: l.currency }), (l.planned_minor / 100).toFixed(2));
    if (!v) return;
    try {
      await api.post(`/api/finance/budget-lines/${l.id}/approve`, { approved: Number(v.replace(/,/g, "")).toFixed(2) });
      lines.reload();
      onChange();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const ms = (tlData.data?.milestones || []).filter((m: Json) => !form?.program_id || String(m.program_id) === String(form.program_id));
  return (
    <div>
      <div className="alert warning"><span>!</span><span>{t("Budget amounts are planning assumptions entered by your team (with estimate source and assumptions). The app does not supply authoritative development costs.")}</span></div>
      <div className="row" style={{ marginBottom: 10 }}><button className="primary" onClick={() => setForm({ ...empty })}>+ {t("Add budget line")}</button></div>
      {form && (
        <div className="card">
          <h3>{form.id ? t("Edit budget line") : t("New budget line")}</h3>
          <div className="form-grid">
            <label className="f">{t("Program (blank = shared company cost)")}<select value={form.program_id} onChange={(e) => setForm({ ...form, program_id: e.target.value, milestone_id: "" })}><option value="">{t("Shared / company")}</option>{(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}</select></label>
            <label className="f">{t("Milestone")}<select value={form.milestone_id} onChange={(e) => setForm({ ...form, milestone_id: e.target.value })}><option value="">—</option>{ms.map((m: Json) => <option key={m.id} value={m.id}>{m.program_code}: {m.name}</option>)}</select></label>
            <label className="f">{t("Category")}<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{(ref.data?.categories || []).map((c: string) => <option key={c} value={c}>{t(c)}</option>)}</select></label>
            <label className="f">{t("Currency")}<select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>{["USD", "HKD", "CNY"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className="f">{t("Planned amount")}<input value={form.planned} onChange={(e) => setForm({ ...form, planned: e.target.value })} inputMode="decimal" /></label>
            <label className="f">{t("Contingency %")}<input value={form.contingency_pct} onChange={(e) => setForm({ ...form, contingency_pct: e.target.value })} inputMode="decimal" /></label>
            <label className="f">{t("Cash-out starts (month)")}<input type="month" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></label>
            <label className="f">{t("Spread over months")}<input type="number" min={1} max={36} value={form.months} onChange={(e) => setForm({ ...form, months: e.target.value })} /></label>
            <label className="f">{t("Owner")}<input value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} /></label>
            <label className="f">{t("Estimate source")}<input value={form.estimate_source} onChange={(e) => setForm({ ...form, estimate_source: e.target.value })} placeholder={t("e.g. CRO quote v2")} /></label>
          </div>
          <label className="f" style={{ marginTop: 8 }}>{t("Assumptions")}<textarea value={form.assumptions} onChange={(e) => setForm({ ...form, assumptions: e.target.value })} /></label>
          {err && <ErrorBox error={err} />}
          <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={save} disabled={!form.planned}>{t("Save as draft")}</button><button onClick={() => setForm(null)}>{t("Cancel")}</button></div>
          <div className="tiny muted">{t("The monthly cash-out schedule is spread evenly; the forecast distributes remaining cost along this schedule.")}</div>
        </div>
      )}
      {!form && err && <ErrorBox error={err} />}
      {lines.loading && <Loading />}
      {lines.data && lines.data.length === 0 && <Empty title={t("No budget lines")}>{t("Add milestone-level budgets to forecast cash needs.")}</Empty>}
      {lines.data && lines.data.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>{t("Program / milestone")}</th><th>{t("Category")}</th><th className="n">{t("Planned")}</th><th className="n">{t("Approved")}</th><th className="n">{t("Contingency")}</th><th>{t("Schedule")}</th><th>{t("Status")}</th><th>{t("Source and assumptions")}</th><th /></tr></thead>
              <tbody>{lines.data.map((l: Json) => {
                const months = Object.keys(l.schedule);
                return (
                  <tr key={l.id}>
                    <td><b>{l.program_code || t("Shared / company")}</b><div className="small">{l.milestone_name || "—"}</div></td>
                    <td>{t(l.category)}</td>
                    <td className="n">{money(l.planned_minor, l.currency)}</td>
                    <td className="n">{l.approved_minor != null ? money(l.approved_minor, l.currency) : <span className="muted">{t("not approved")}</span>}</td>
                    <td className="n">{l.contingency_bps / 100}%</td>
                    <td className="small">{months.length ? `${months[0]} → ${months[months.length - 1]} (${t("{n} mo", { n: months.length })})` : <span className="muted">{t("none")}</span>}</td>
                    <td><StatusPill status={l.status} /></td>
                    <td className="small" style={{ maxWidth: 280 }}><Prov kind={l.origin === "synthetic" ? "synthetic" : "assumption"} /> {l.estimate_source}<div className="tiny muted">{l.assumptions}</div></td>
                    <td>
                      <div className="row">
                        <button className="link small" onClick={() => setForm({ id: l.id, program_id: l.program_id || "", milestone_id: l.milestone_id || "", category: l.category, description: l.description || "", currency: l.currency, planned: (l.planned_minor / 100).toFixed(2), contingency_pct: String(l.contingency_bps / 100), owner: l.owner || "", estimate_source: l.estimate_source || "", assumptions: l.assumptions || "", start: months[0] || "", months: String(months.length || 1) })}>{t("Edit")}</button>
                        {l.status !== "closed" && <button className="link small" onClick={() => approve(l)}>{l.status === "approved" ? t("Re-approve") : t("Approve")}</button>}
                        {l.status === "draft" && <button className="link small" style={{ color: "var(--bad)" }} onClick={async () => { await api.del(`/api/finance/budget-lines/${l.id}`); lines.reload(); onChange(); }}>{t("Delete")}</button>}
                        {l.status === "approved" && <button className="link small" onClick={async () => { await api.post(`/api/finance/budget-lines/${l.id}/close`); lines.reload(); onChange(); }}>{t("Close")}</button>}
                      </div>
                    </td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------- transactions

function Transactions({ onChange }: { onChange: () => void }) {
  const { t, tl } = useI18n();
  const [alloc, setAlloc] = useState("");
  const [kind, setKind] = useState("");
  const tx = useApi(`/api/finance/transactions?limit=1000${alloc ? `&allocation=${alloc}` : ""}${kind ? `&kind=${kind}` : ""}`);
  const progs = useApi("/api/programs");
  const ref = useApi("/api/reference");
  const tlData = useApi("/api/timeline");
  const patch = async (id: number, body: Json) => {
    await api.patch(`/api/finance/transactions/${id}`, body);
    tx.reload();
    onChange();
  };
  const KINDS = ["operating", "refund", "financing", "transfer"];
  return (
    <div className="card">
      <div className="pill-filter">
        <label className="f">{t("Allocation")}<select value={alloc} onChange={(e) => setAlloc(e.target.value)}><option value="">{t("All")}</option>{["unallocated", "shared", "direct"].map((a) => <option key={a} value={a}>{tl(a)}</option>)}</select></label>
        <label className="f">{t("Flow type")}<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">{t("All")}</option>{KINDS.map((k) => <option key={k} value={k}>{tl(k)}</option>)}</select></label>
        <span className="small muted">{t("Edits are logged with before/after values. Reversed import batches are excluded.")}</span>
      </div>
      {tx.loading && <Loading />}
      {tx.data && tx.data.length === 0 && <Empty title={t("No transactions")}>{t("Import a CSV or XLSX file.")}</Empty>}
      {tx.data && tx.data.length > 0 && (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>{t("Date")}</th><th className="n">{t("Amount")}</th><th>{t("Type")}</th><th>{t("Description")}</th><th>{t("Account")}</th><th>{t("Category")}</th><th>{t("Program")}</th><th>{t("Milestone")}</th><th>{t("Allocation")}</th><th>{t("Source")}</th></tr></thead>
            <tbody>{tx.data.map((x: Json) => (
              <tr key={x.id}>
                <td className="small">{x.txn_date}</td>
                <td className="n">{x.direction === "outflow" ? "−" : "+"}{money(x.amount_minor, x.currency)}</td>
                <td><select value={x.kind} onChange={(e) => patch(x.id, { kind: e.target.value })} aria-label={t("Flow type")}>{KINDS.map((k) => <option key={k} value={k}>{tl(k)}</option>)}</select></td>
                <td className="small" style={{ maxWidth: 220 }}>{x.description}<div className="tiny muted">{x.counterparty}</div></td>
                <td className="small">{x.account_name || <span style={{ color: "var(--warn)" }}>{t("none")}</span>}</td>
                <td><select value={x.category || ""} onChange={(e) => patch(x.id, { category: e.target.value || null })} aria-label={t("Category")}><option value="">—</option>{(ref.data?.categories || []).map((c: string) => <option key={c} value={c}>{t(c)}</option>)}</select></td>
                <td><select value={x.program_id || ""} onChange={(e) => patch(x.id, e.target.value ? { program_id: Number(e.target.value) } : { program_id: null, milestone_id: null, allocation: "unallocated" })} aria-label={t("Program")}><option value="">—</option>{(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}</select></td>
                <td><select value={x.milestone_id || ""} onChange={(e) => patch(x.id, { milestone_id: e.target.value ? Number(e.target.value) : null })} aria-label={t("Milestone")} disabled={!x.program_id}><option value="">—</option>{(tlData.data?.milestones || []).filter((m: Json) => m.program_id === x.program_id).map((m: Json) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></td>
                <td><select value={x.allocation} onChange={(e) => patch(x.id, { allocation: e.target.value })} aria-label={t("Allocation")}>{["direct", "shared", "unallocated"].map((a) => <option key={a} value={a}>{tl(a)}</option>)}</select></td>
                <td className="tiny"><Prov kind={x.origin} />{x.batch_id && <div className="muted">{t("batch {b} row {r}", { b: x.batch_id, r: x.source_row })}</div>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ cash/fx

function CashFx({ onChange }: { onChange: () => void }) {
  const { t, tl } = useI18n();
  const acc = useApi("/api/finance/accounts");
  const fx = useApi("/api/finance/fx");
  const st = useApi("/api/finance/settings");
  const [a, setA] = useState<Json>({ name: "", legal_entity: "", entity_base_currency: "HKD", currency: "HKD" });
  const [b, setB] = useState<Json>({ account_id: "", as_of_date: "", balance: "", source: "" });
  const [r, setR] = useState<Json>({ base: "USD", quote: "HKD", rate: "", rate_date: "", source: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const act = async (fn: () => Promise<Json>, ok: string) => {
    setErr(null);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      acc.reload(); fx.reload(); st.reload(); onChange();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const s = st.data;
  return (
    <div>
      {err && <ErrorBox error={err} />}
      {msg && <div className="alert good">✓ {msg}</div>}
      <div className="grid g2">
        <div className="card">
          <h2>{t("Reporting settings")}</h2>
          {s && <SettingsForm s={s} onSave={(body) => act(() => api.put("/api/finance/settings", body), t("Settings saved"))} />}
        </div>
        <div className="card">
          <h2>{t("Reconciled balances (required for cash and runway)")}</h2>
          <div className="form-grid">
            <label className="f">{t("Account")}<select value={b.account_id} onChange={(e) => setB({ ...b, account_id: e.target.value })}><option value="">—</option>{(acc.data?.accounts || []).map((x: Json) => <option key={x.id} value={x.id}>{x.name} ({x.currency})</option>)}</select></label>
            <label className="f">{t("Reconciliation date")}<input type="date" value={b.as_of_date} onChange={(e) => setB({ ...b, as_of_date: e.target.value })} /></label>
            <label className="f">{t("Balance (account currency)")}<input value={b.balance} onChange={(e) => setB({ ...b, balance: e.target.value })} /></label>
            <label className="f">{t("Source")}<input value={b.source} onChange={(e) => setB({ ...b, source: e.target.value })} placeholder={t("bank statement")} /></label>
          </div>
          <button style={{ marginTop: 8 }} disabled={!b.account_id || !b.as_of_date || !b.balance} onClick={() => act(() => api.post("/api/finance/balances", { ...b, account_id: Number(b.account_id), balance: Number(b.balance.replace(/,/g, "")).toFixed(2) }), t("Balance recorded"))}>{t("Record balance")}</button>
          <table className="t" style={{ marginTop: 10 }}><tbody>{(acc.data?.balances || []).slice(0, 8).map((x: Json) => <tr key={x.id}><td>{(acc.data.accounts.find((y: Json) => y.id === x.account_id) || {}).name}</td><td>{x.as_of_date}</td><td className="n">{money(x.balance_minor, x.currency)}</td><td className="small muted">{x.source}</td></tr>)}</tbody></table>
        </div>
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>{t("Accounts and legal entities")}</h2>
          <table className="t"><thead><tr><th>{t("Account")}</th><th>{t("Entity")}</th><th>{t("Currency")}</th></tr></thead><tbody>{(acc.data?.accounts || []).map((x: Json) => <tr key={x.id}><td>{x.name} {x.origin === "synthetic" && <Prov kind="synthetic" />}</td><td>{x.legal_entity}</td><td>{x.currency}</td></tr>)}</tbody></table>
          <div className="form-grid" style={{ marginTop: 10 }}>
            <label className="f">{t("Account name")}<input value={a.name} onChange={(e) => setA({ ...a, name: e.target.value })} /></label>
            <label className="f">{t("Legal entity")}<input value={a.legal_entity} onChange={(e) => setA({ ...a, legal_entity: e.target.value })} /></label>
            <label className="f">{t("Account currency")}<select value={a.currency} onChange={(e) => setA({ ...a, currency: e.target.value, entity_base_currency: e.target.value })}>{["HKD", "CNY", "USD"].map((c) => <option key={c}>{c}</option>)}</select></label>
          </div>
          <button style={{ marginTop: 8 }} disabled={!a.name || !a.legal_entity} onClick={() => act(() => api.post("/api/finance/accounts", a), t("Account added"))}>{t("Add account")}</button>
        </div>
        <div className="card">
          <div className="card-head"><h2>{t("Exchange rates")}</h2><button onClick={() => act(() => api.post("/api/finance/fx/fetch-ecb"), t("Fetched ECB reference rates"))}>{t("Fetch ECB reference rates")}</button></div>
          <div className="form-grid">
            <label className="f">{t("1 unit of")}<select value={r.base} onChange={(e) => setR({ ...r, base: e.target.value })}>{["USD", "HKD", "CNY", "EUR"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className="f">{t("= rate in")}<select value={r.quote} onChange={(e) => setR({ ...r, quote: e.target.value })}>{["HKD", "CNY", "USD", "EUR"].map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className="f">{t("Rate")}<input value={r.rate} onChange={(e) => setR({ ...r, rate: e.target.value })} inputMode="decimal" /></label>
            <label className="f">{t("Rate date")}<input type="date" value={r.rate_date} onChange={(e) => setR({ ...r, rate_date: e.target.value })} /></label>
            <label className="f">{t("Source")}<input value={r.source} onChange={(e) => setR({ ...r, source: e.target.value })} placeholder={t("e.g. bank confirmation")} /></label>
          </div>
          <button style={{ marginTop: 8 }} disabled={!r.rate || !r.rate_date || !r.source} onClick={() => act(() => api.post("/api/finance/fx", r), t("Manual rate saved"))}>{t("Save manual rate")}</button>
          <div className="table-wrap" style={{ marginTop: 10, maxHeight: 220 }}>
            <table className="t"><thead><tr><th>{t("Pair")}</th><th className="n">{t("Rate")}</th><th>{t("Date")}</th><th>{t("Source")}</th><th>{t("Method")}</th></tr></thead><tbody>{(fx.data?.rates || []).map((x: Json) => <tr key={x.id}><td>{x.base}/{x.quote}</td><td className="n">{x.rate}</td><td>{x.rate_date}</td><td className="small">{x.source}</td><td><Badge>{tl(x.method)}</Badge></td></tr>)}</tbody></table>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsForm({ s, onSave }: { s: Json; onSave: (b: Json) => void }) {
  const { t } = useI18n();
  const [v, setV] = useState<Json>({ reporting_currency: s.reporting_currency, min_reserve: (s.min_reserve_minor / 100).toFixed(2), burn_period_months: s.burn_period_months, horizon_months: s.horizon_months, timezone: s.timezone, as_of_override: s.as_of_override || "" });
  return (
    <div>
      <div className="form-grid">
        <label className="f">{t("Reporting currency")}<select value={v.reporting_currency} onChange={(e) => setV({ ...v, reporting_currency: e.target.value })}>{["USD", "HKD", "CNY"].map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="f">{t("Minimum cash reserve ({c})", { c: v.reporting_currency })}<input value={v.min_reserve} onChange={(e) => setV({ ...v, min_reserve: e.target.value })} /></label>
        <label className="f">{t("Burn period (months)")}<input type="number" min={1} max={24} value={v.burn_period_months} onChange={(e) => setV({ ...v, burn_period_months: Number(e.target.value) })} /></label>
        <label className="f">{t("Forecast horizon (months)")}<input type="number" min={3} max={60} value={v.horizon_months} onChange={(e) => setV({ ...v, horizon_months: Number(e.target.value) })} /></label>
        <label className="f">{t("Timezone (briefing day)")}<input value={v.timezone} onChange={(e) => setV({ ...v, timezone: e.target.value })} /></label>
        <label className="f">{t("As-of date override (blank = today)")}<input type="date" value={v.as_of_override} onChange={(e) => setV({ ...v, as_of_override: e.target.value })} /></label>
      </div>
      <button className="primary" style={{ marginTop: 8 }} onClick={() => onSave({ reporting_currency: v.reporting_currency, min_reserve: Number(String(v.min_reserve).replace(/,/g, "")).toFixed(2), burn_period_months: v.burn_period_months, horizon_months: v.horizon_months, timezone: v.timezone, ...(v.as_of_override ? { as_of_override: v.as_of_override } : { clear_as_of_override: true }) })}>{t("Save settings")}</button>
    </div>
  );
}

// -------------------------------------------------------------- commitments

function Commitments({ onChange }: { onChange: () => void }) {
  const { t, tl } = useI18n();
  const cm = useApi("/api/finance/commitments");
  const fl = useApi("/api/finance/planned-flows");
  const rules = useApi("/api/finance/allocation-rules");
  const progs = useApi("/api/programs");
  const tlData = useApi("/api/timeline");
  const ref = useApi("/api/reference");
  const [c, setC] = useState<Json>({ program_id: "", milestone_id: "", category: "CRO services", counterparty: "", description: "", currency: "USD", amount: "", expected_payment_date: "" });
  const [f, setF] = useState<Json>({ label: "", flow_date: "", amount: "", currency: "USD", direction: "inflow", kind: "financing", certainty: "hypothetical" });
  const [rule, setRule] = useState<Json>({ name: "", category: "", shares: {} });
  const [err, setErr] = useState<string | null>(null);
  const act = async (fn: () => Promise<Json>) => {
    setErr(null);
    try {
      await fn();
      cm.reload(); fl.reload(); rules.reload(); onChange();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const link = (id: number) => {
    const x = window.prompt(t("Transaction id that paid this commitment (see Transactions tab):"));
    if (x) act(() => api.post(`/api/finance/commitments/${id}/link-payment?transaction_id=${Number(x)}`));
  };
  return (
    <div>
      {err && <ErrorBox error={err} />}
      <div className="card">
        <h2>{t("Commitments (unpaid, contracted)")}</h2>
        <div className="tiny muted" style={{ marginBottom: 8 }}>{t("Kept separate from paid actuals. When paid, link the payment so it moves from \"committed\" to \"actual\" and is counted once.")}</div>
        <table className="t">
          <thead><tr><th>{t("Counterparty")}</th><th>{t("Program / milestone")}</th><th>{t("Category")}</th><th className="n">{t("Amount")}</th><th>{t("Expected payment")}</th><th>{t("Status")}</th><th /></tr></thead>
          <tbody>{(cm.data || []).map((x: Json) => (
            <tr key={x.id}><td>{x.counterparty}<div className="tiny muted">{x.description}</div></td><td className="small">{x.program_code || "—"} · {x.milestone_name || "—"}</td><td>{x.category ? t(x.category) : "—"}</td><td className="n">{money(x.amount_minor, x.currency)}</td><td>{dateOnly(x.expected_payment_date)}</td><td><StatusPill status={x.status} />{x.paid_transaction_id && <div className="tiny muted">{t("paid by txn {n}", { n: x.paid_transaction_id })}</div>}</td>
              <td>{x.status === "open" && <div className="row"><button className="link small" onClick={() => link(x.id)}>{t("Link payment")}</button><button className="link small" onClick={() => act(() => api.post(`/api/finance/commitments/${x.id}/cancel`))}>{t("Cancel")}</button></div>}</td></tr>))}</tbody>
        </table>
        <div className="form-grid" style={{ marginTop: 10 }}>
          <label className="f">{t("Program")}<select value={c.program_id} onChange={(e) => setC({ ...c, program_id: e.target.value })}><option value="">—</option>{(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}</select></label>
          <label className="f">{t("Milestone")}<select value={c.milestone_id} onChange={(e) => setC({ ...c, milestone_id: e.target.value })}><option value="">—</option>{(tlData.data?.milestones || []).filter((m: Json) => String(m.program_id) === String(c.program_id)).map((m: Json) => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <label className="f">{t("Category")}<select value={c.category} onChange={(e) => setC({ ...c, category: e.target.value })}>{(ref.data?.categories || []).map((x: string) => <option key={x} value={x}>{t(x)}</option>)}</select></label>
          <label className="f">{t("Counterparty")}<input value={c.counterparty} onChange={(e) => setC({ ...c, counterparty: e.target.value })} /></label>
          <label className="f">{t("Currency")}<select value={c.currency} onChange={(e) => setC({ ...c, currency: e.target.value })}>{["USD", "HKD", "CNY"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="f">{t("Amount")}<input value={c.amount} onChange={(e) => setC({ ...c, amount: e.target.value })} /></label>
          <label className="f">{t("Expected payment")}<input type="date" value={c.expected_payment_date} onChange={(e) => setC({ ...c, expected_payment_date: e.target.value })} /></label>
          <label className="f">{t("Description")}<input value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} /></label>
        </div>
        <button style={{ marginTop: 8 }} disabled={!c.counterparty || !c.amount} onClick={() => act(() => api.post("/api/finance/commitments", { ...c, program_id: c.program_id ? Number(c.program_id) : null, milestone_id: c.milestone_id ? Number(c.milestone_id) : null, amount: Number(c.amount.replace(/,/g, "")).toFixed(2), expected_payment_date: c.expected_payment_date || null, description: c.description || null }))}>{t("Add commitment")}</button>
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>{t("Planned flows (grants, financing, other)")}</h2>
          <div className="tiny muted">{t("Hypothetical flows appear only in scenarios until you confirm them.")}</div>
          <table className="t"><tbody>{(fl.data || []).map((x: Json) => <tr key={x.id}><td>{x.flow_date}</td><td>{x.label}</td><td className="n">{x.direction === "inflow" ? "+" : "−"}{money(x.amount_minor, x.currency)}</td><td><StatusPill status={x.certainty} /></td><td>{x.certainty === "hypothetical" && <button className="link small" onClick={() => window.confirm(t("Confirm this flow? It will be included in the baseline forecast.")) && act(() => api.post(`/api/finance/planned-flows/${x.id}/confirm`))}>{t("Confirm")}</button>}</td></tr>)}</tbody></table>
          <div className="form-grid" style={{ marginTop: 10 }}>
            <label className="f">{t("Label")}<input value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} /></label>
            <label className="f">{t("Date")}<input type="date" value={f.flow_date} onChange={(e) => setF({ ...f, flow_date: e.target.value })} /></label>
            <label className="f">{t("Amount")}<input value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></label>
            <label className="f">{t("Currency")}<select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>{["USD", "HKD", "CNY"].map((x) => <option key={x}>{x}</option>)}</select></label>
            <label className="f">{t("Direction")}<select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}>{["inflow", "outflow"].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select></label>
            <label className="f">{t("Kind")}<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["financing", "operating"].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select></label>
            <label className="f">{t("Certainty")}<select value={f.certainty} onChange={(e) => setF({ ...f, certainty: e.target.value })}>{["hypothetical", "confirmed"].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select></label>
          </div>
          <button style={{ marginTop: 8 }} disabled={!f.label || !f.flow_date || !f.amount} onClick={() => act(() => api.post("/api/finance/planned-flows", { ...f, amount: Number(f.amount.replace(/,/g, "")).toFixed(2) }))}>{t("Add planned flow")}</button>
        </div>
        <div className="card">
          <h2>{t("Shared-cost allocation rules")}</h2>
          <div className="tiny muted">{t("Shared expenses are split across programs only by explicit rules (shares must total 100%). Without a rule they stay in the shared pool.")}</div>
          <table className="t"><tbody>{(rules.data || []).map((x: Json) => <tr key={x.id}><td>{x.name}</td><td>{x.category ? t(x.category) : t("all shared")}</td><td className="small">{Object.entries(x.shares).map(([pid, bps]) => `${(progs.data || []).find((p: Json) => String(p.id) === pid)?.code || pid}: ${(bps as number) / 100}%`).join(", ")}</td><td>{x.active ? <StatusPill status="active" /> : t("inactive")}</td></tr>)}</tbody></table>
          <div className="form-grid" style={{ marginTop: 10 }}>
            <label className="f">{t("Rule name")}<input value={rule.name} onChange={(e) => setRule({ ...rule, name: e.target.value })} /></label>
            <label className="f">{t("Category (blank = all)")}<select value={rule.category} onChange={(e) => setRule({ ...rule, category: e.target.value })}><option value="">{t("all shared")}</option>{(ref.data?.categories || []).map((x: string) => <option key={x} value={x}>{t(x)}</option>)}</select></label>
            {(progs.data || []).map((p: Json) => <label key={p.id} className="f">{p.code} %<input value={rule.shares[p.id] || ""} onChange={(e) => setRule({ ...rule, shares: { ...rule.shares, [p.id]: e.target.value } })} /></label>)}
          </div>
          <button style={{ marginTop: 8 }} disabled={!rule.name} onClick={() => act(() => api.post("/api/finance/allocation-rules", { name: rule.name, category: rule.category || null, shares_pct: Object.fromEntries(Object.entries(rule.shares).filter(([, v]) => v).map(([k, v]) => [k, Number(v).toFixed(2)])) }))}>{t("Add rule")}</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- scenarios

function Scenarios() {
  const { t, tl } = useI18n();
  const sc = useApi("/api/finance/scenarios");
  const tlData = useApi("/api/timeline");
  const [sel, setSel] = useState<number | null>(null);
  const cmp = useApi(sel ? `/api/finance/scenarios/${sel}/compare` : null, [sel]);
  const [form, setForm] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const [funding, setFunding] = useState<Json>(null);
  const openMs = (tlData.data?.milestones || []).filter((m: Json) => !["done", "cancelled"].includes(m.status));
  const create = async () => {
    setErr(null);
    const a: Json = {};
    if (form.milestone_id && form.shift) a.milestone_shifts = { [form.milestone_id]: Number(form.shift) };
    if (form.category && form.pct) a.category_cost_change_pct = { [form.category]: Number(form.pct) };
    if (form.fin_amount && form.fin_date) a.financing = [{ label: form.fin_label || "Hypothetical financing", date: form.fin_date, amount: Number(form.fin_amount.replace(/,/g, "")).toFixed(2), currency: form.fin_ccy }];
    if (form.include_hyp) a.include_hypothetical_planned_flows = true;
    try {
      const s = await api.post("/api/finance/scenarios", { name: form.name, kind: "custom", description: form.description || null, assumptions: a });
      setForm(null);
      sc.reload();
      setSel(s.id);
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const checkFunding = async (mid: string) => {
    if (!mid || !sel) return;
    const [b, s] = await Promise.all([api.get(`/api/finance/milestones/${mid}/funding`), api.get(`/api/finance/milestones/${mid}/funding?scenario_id=${sel}`)]);
    setFunding({ b, s });
  };
  const ccy = cmp.data?.currency || "USD";
  const scen = (sc.data?.scenarios || []).find((s: Json) => s.id === sel);
  return (
    <div>
      <div className="alert info"><span>i</span><span>{t("Scenarios are calculated on a copy of the plan. They never change the approved baseline, budgets, or milestones. Hypothetical financing stays in scenarios until confirmed under Commitments and flows.")}</span></div>
      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>{t("Scenarios")}</h2><button onClick={() => setForm({ name: "", milestone_id: "", shift: "3", category: "", pct: "", fin_amount: "", fin_date: "", fin_ccy: "USD", fin_label: "", include_hyp: false })}>+ {t("New scenario")}</button></div>
          {sc.loading && <Loading />}
          {!sel && <div className="small muted" style={{ marginBottom: 6 }}>{t("Click a scenario to compare it with the approved plan.")}</div>}
          <table className="t">
            <tbody>{(sc.data?.scenarios || []).map((s: Json) => (
              <tr key={s.id} style={{ background: s.id === sel ? "var(--teal-100)" : undefined }}>
                <td><button className="link" onClick={() => { setSel(s.id); setFunding(null); }}>{t(s.name)}</button><div className="tiny muted">{t(s.description || "")}</div></td>
                <td><Badge>{tl(s.kind)}</Badge> <Prov kind="assumption" /></td>
                <td>{s.kind !== "base" && <button className="link small" style={{ color: "var(--bad)" }} onClick={async () => { await api.del(`/api/finance/scenarios/${s.id}`); if (sel === s.id) setSel(null); sc.reload(); }}>{t("Delete")}</button>}</td>
              </tr>))}</tbody>
          </table>
        </div>
        {form && (
          <div className="card">
            <h2>{t("New scenario (assumptions)")}</h2>
            <div className="form-grid">
              <label className="f">{t("Name")}<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label className="f">{t("Delay milestone")}<select value={form.milestone_id} onChange={(e) => setForm({ ...form, milestone_id: e.target.value })}><option value="">—</option>{openMs.map((m: Json) => <option key={m.id} value={m.id}>{m.program_code}: {m.name}</option>)}</select></label>
              <label className="f">{t("by months (negative = earlier)")}<input type="number" value={form.shift} onChange={(e) => setForm({ ...form, shift: e.target.value })} /></label>
              <label className="f">{t("Change cost category")}<select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}><option value="">—</option>{["CRO services", "Clinical / field studies", "Manufacturing / CMC", "Preclinical studies", "Research", "Personnel"].map((c) => <option key={c} value={c}>{t(c)}</option>)}</select></label>
              <label className="f">{t("by %")}<input value={form.pct} onChange={(e) => setForm({ ...form, pct: e.target.value })} /></label>
              <label className="f">{t("Hypothetical financing amount")}<input value={form.fin_amount} onChange={(e) => setForm({ ...form, fin_amount: e.target.value })} /></label>
              <label className="f">{t("on date")}<input type="date" value={form.fin_date} onChange={(e) => setForm({ ...form, fin_date: e.target.value })} /></label>
              <label className="f">{t("currency")}<select value={form.fin_ccy} onChange={(e) => setForm({ ...form, fin_ccy: e.target.value })}>{["USD", "HKD", "CNY"].map((c) => <option key={c}>{c}</option>)}</select></label>
              <label className="row small"><input type="checkbox" checked={form.include_hyp} onChange={(e) => setForm({ ...form, include_hyp: e.target.checked })} /> {t("include hypothetical planned flows")}</label>
            </div>
            {err && <ErrorBox error={err} />}
            <div className="row" style={{ marginTop: 8 }}><button className="primary" disabled={!form.name} onClick={create}>{t("Create and compare")}</button><button onClick={() => setForm(null)}>{t("Cancel")}</button></div>
          </div>
        )}
      </div>
      {sel && (
        <div className="card">
          <h2>{t("Baseline vs {s}", { s: t(scen?.name || "") })}</h2>
          {cmp.loading && <Loading />}
          {cmp.error && <ErrorBox error={cmp.error} />}
          {cmp.data && (
            <>
              <div className="grid g3" style={{ marginBottom: 12 }}>
                <Stat k={t("Below reserve")} v={`${cmp.data.comparison.below_reserve_month.base || "—"} → ${cmp.data.comparison.below_reserve_month.scenario || "—"}`} d={t("baseline → scenario")} />
                <Stat k={t("Lowest projected cash")} v={money(cmp.data.comparison.min_cash_minor.scenario, ccy, { compact: true })} d={t("baseline {b} · Δ {d}", { b: money(cmp.data.comparison.min_cash_minor.base, ccy, { compact: true }), d: money(cmp.data.comparison.min_cash_minor.delta, ccy, { compact: true }) })} />
                <Stat k={t("Cash at horizon")} v={money(cmp.data.comparison.cash_at_horizon_minor.scenario, ccy, { compact: true })} d={t("baseline {b}", { b: money(cmp.data.comparison.cash_at_horizon_minor.base, ccy, { compact: true }) })} />
              </div>
              <CashForecastChart months={cmp.data.comparison.months.map((m: Json) => ({ month: m.month, closing_minor: m.base_closing_minor }))} reserve={cmp.data.reserve_minor} ccy={ccy} scenario={cmp.data.comparison.months} scenarioName={t(scen?.name || "")} />
              <div className="section-label">{t("Assumptions")}</div>
              <pre className="trace">{JSON.stringify(cmp.data.scenario.assumptions, null, 2)}</pre>
              <div className="tiny muted">{t("Scenario results are computed on a copy. The approved baseline, budgets and milestones are unchanged.")}</div>
              <div className="section-label">{t("Milestone funding under this scenario")}</div>
              <select onChange={(e) => checkFunding(e.target.value)} defaultValue="" aria-label={t("Choose milestone")}><option value="">{t("Choose a milestone…")}</option>{openMs.map((m: Json) => <option key={m.id} value={m.id}>{m.program_code}: {m.name}</option>)}</select>
              {funding && (
                <table className="t" style={{ marginTop: 8 }}>
                  <thead><tr><th /><th>{t("Funded?")}</th><th className="n">{t("Direct cost to reach")}</th><th className="n">{t("Lowest cash through milestone")}</th><th className="n">{t("Gap")}</th></tr></thead>
                  <tbody>{[[t("Baseline"), funding.b], [t("Scenario"), funding.s]].map(([n, f]: Json) => <tr key={n}><td>{n}</td><td>{f.funded === true ? <Badge tone="good">✓ {t("yes")}</Badge> : f.funded === false ? <Badge tone="bad">✕ {t("no")}</Badge> : t("unknown")}</td><td className="n">{money(f.direct_cost_to_reach_minor, f.currency)}</td><td className="n">{money(f.min_projected_cash_through_milestone_minor, f.currency)}</td><td className="n">{money(f.funding_gap_minor, f.currency)}</td></tr>)}</tbody>
                </table>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
