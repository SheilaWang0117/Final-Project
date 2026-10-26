import { Link } from "react-router-dom";
import type { Json } from "../api";
import { CashForecastChart, ChartMeta } from "../components/charts";
import { Cat, Dog, Paw, PawTrail } from "../components/pets";
import { Empty, ErrorBox, Loading, Prov, Source, Stat, StatusPill, useApi } from "../components/ui";
import { ago, dateOnly, money } from "../format";
import { useI18n } from "../i18n";

function Mission() {
  const { t } = useI18n();
  const { data } = useApi("/api/settings/company");
  const values: string[] = data?.values || ["All life matters"];
  return (
    <section className="mission" aria-label={t("Our mission and values")}>
      <div className="mission-pets" aria-hidden>
        <Cat size={58} />
        <Dog size={58} />
      </div>
      <div className="mission-body">
        <div className="mission-kicker">{t("Why we are here")}</div>
        <div className="mission-value">{values.map((v) => t(v)).join(" · ")}</div>
        <div className="mission-text">
          {data?.mission ? data.mission : (
            <>
              {t("Bring better cancer medicines to dogs, cats and the families who love them.")}{" "}
              <Link to="/settings" className="tiny">{t("Draft mission — edit it in Settings")}</Link>
            </>
          )}
        </div>
      </div>
      <PawTrail n={6} color="rgba(255,255,255,0.35)" />
    </section>
  );
}

function AskCard({ to, q, a, tone = "neutral", cta }: { to: string; q: string; a: React.ReactNode; tone?: "good" | "warn" | "bad" | "neutral"; cta: string }) {
  return (
    <Link to={to} className={`ask-card tone-${tone}`}>
      <div className="ask-q">{q}</div>
      <div className="ask-a">{a}</div>
      <div className="ask-cta">{cta} <Paw size={11} /></div>
    </Link>
  );
}

export default function Overview() {
  const { t, lang } = useI18n();
  const sum = useApi("/api/finance/summary");
  const tl = useApi("/api/timeline");
  const progs = useApi("/api/programs");
  const ev = useApi("/api/events?days=30");
  const acts = useApi("/api/actions?status=proposed");
  const brief = useApi("/api/briefing");
  const reg = useApi("/api/regulatory/documents");
  const partners = useApi("/api/partners");
  if (sum.error) return <ErrorBox error={sum.error} onRetry={sum.reload} />;
  if (!sum.data || !tl.data || !progs.data) return <><Mission /><Loading /></>;
  const s: Json = sum.data;
  const ccy = s.currency;
  const fc = s.forecast;
  const open = (tl.data.milestones as Json[]).filter((m) => !["done", "cancelled"].includes(m.status));
  const nextByProgram: Json[] = [];
  for (const p of progs.data as Json[]) {
    const m = open.filter((x) => x.program_id === p.id).sort((a, b) => (a.planned_end || "9").localeCompare(b.planned_end || "9"))[0];
    if (m) nextByProgram.push({ p, m });
  }
  const gaps = nextByProgram.filter((x) => x.m.funding?.funded === false);
  const funded = nextByProgram.filter((x) => x.m.funding?.funded === true);
  const stories = brief.data?.briefing?.items?.stories || [];
  const needsReview = (reg.data || []).filter((d: Json) => d.review_status === "needs_review").length;
  const topPartner = partners.data?.partners?.[0];
  return (
    <div>
      <Mission />
      <h2 className="section-title">{t("What do you want to know?")}</h2>
      <div className="ask-grid">
        <AskCard to="/budget" q={t("Can we fund our next milestones?")} tone={gaps.length ? "bad" : funded.length ? "good" : "neutral"} cta={t("Open Budget and Runway")}
          a={gaps.length ? t("{n} next milestone(s) have a funding gap", { n: gaps.length }) : funded.length ? t("Next milestones are funded") : t("Not enough data yet")} />
        <AskCard to="/budget" q={t("How long does our cash last?")} tone={fc.below_reserve_month ? "warn" : "neutral"} cta={t("See the cash forecast")}
          a={fc.start_cash_minor == null ? t("Cash balance incomplete") : fc.below_reserve_month ? t("Below reserve in {m}", { m: fc.below_reserve_month }) : t("Above reserve for the whole forecast")} />
        <AskCard to="/pipelines" q={t("What are we developing, and what is next?")} cta={t("Open Pipelines")}
          a={t("{p} programs · {o} open milestones", { p: progs.data.length, o: open.length })} tone={open.some((m) => m.overdue) ? "warn" : "neutral"} />
        <AskCard to="/briefing" q={t("What is new today?")} cta={t("Read the briefing")}
          a={brief.data?.briefing ? t("{n} stories · {d}", { n: stories.length, d: brief.data.briefing.briefing_date }) : t("No briefing yet")} tone={brief.data?.stale ? "warn" : "neutral"} />
        <AskCard to="/competitors" q={t("What are competitors doing?")} cta={t("Open Competitor Intelligence")}
          a={ev.data ? t("{n} events in 30 days · {a} actions to review", { n: ev.data.events.length, a: acts.data?.length || 0 }) : "…"} />
        <AskCard to="/regulatory" q={t("Which rules could affect our plans?")} cta={t("Open Regulatory Intelligence")}
          a={reg.data ? t("{n} documents need review", { n: needsReview }) : "…"} tone={needsReview ? "warn" : "neutral"} />
        <AskCard to="/markets" q={t("Who could license our products?")} cta={t("Open Markets and Licensing")}
          a={topPartner ? t("Strongest documented fit: {c} ({s}/100)", { c: topPartner.company, s: topPartner.fit_score }) : t("No partner assessment yet")} />
        <AskCard to="/assistant" q={t("I have a different question")} cta={t("Ask the AI Assistant")} a={t("Answers use our own numbers and cited sources")} />
      </div>

      <h2 className="section-title">{t("Key numbers")} <span className="muted small">· {t("as of {d}", { d: s.as_of })}</span></h2>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Stat to="/budget" k={t("Available cash")} v={s.cash.complete ? money(s.cash.available_cash_minor, ccy, { compact: true }) : t("Incomplete")}
          d={s.cash.complete ? t("Reconciled + later transactions · {n} accounts", { n: s.cash.accounts.length }) : t("Add reconciled balances for every account")} title={s.definitions.available_cash} />
        <Stat to="/budget" k={t("Net burn / month ({n} mo)", { n: s.burn.months })} v={money(s.burn.net_burn_monthly_minor, ccy, { compact: true })}
          d={t("Gross {g} · from {d}", { g: money(s.burn.gross_burn_monthly_minor, ccy, { compact: true }), d: s.burn.period_start })} title={s.definitions.net_burn} />
        <Stat to="/budget" k={t("Simple runway")} v={s.simple_runway.months ? t("{n} months", { n: s.simple_runway.months }) : "n/a"} d={s.simple_runway.months ? t("Cash ÷ historical net burn") : s.simple_runway.note} title={s.definitions.simple_runway} />
        <Stat to="/budget" k={t("Forecast: below reserve")} v={fc.below_reserve_month || (fc.start_cash_minor == null ? t("Incomplete") : t("Not in horizon"))}
          d={t("Reserve {r}", { r: money(fc.reserve_minor, ccy, { compact: true }) }) + (fc.cash_out_month ? ` · ${t("below zero {m}", { m: fc.cash_out_month })}` : "")} title={s.definitions.forecast_runway} />
      </div>
      {s.simple_runway.months && fc.below_reserve_month && (
        <div className="alert info">
          <span>i</span>
          <span>{t("The simple runway uses past spending; the forecast includes planned studies and commitments. When they differ, the forecast is the better guide to future funding needs.")}</span>
        </div>
      )}

      <div className="grid g2">
        <div className="card">
          <div className="card-head">
            <h2>{t("Next milestone per program")}</h2>
            <Link to="/pipelines" className="small">{t("All pipelines →")}</Link>
          </div>
          {nextByProgram.length === 0 ? (
            <Empty title={t("No open milestones")}>{t("Add milestones to a program to see funding status.")}</Empty>
          ) : (
            <table className="t">
              <thead><tr><th>{t("Program")}</th><th>{t("Next milestone")}</th><th>{t("Due")}</th><th>{t("Funded?")}</th><th className="n">{t("Remaining cost")}</th></tr></thead>
              <tbody>
                {nextByProgram.map(({ p, m }) => (
                  <tr key={p.id}>
                    <td><Link to={`/pipelines/${p.id}`}>{p.code}</Link> {p.origin === "synthetic" && <Prov kind="synthetic" />}</td>
                    <td>{m.name} {m.overdue && <StatusPill status="overdue" />}</td>
                    <td>{dateOnly(m.planned_end)}</td>
                    <td>
                      {m.funding?.funded === true ? <StatusPill status="funded" /> : m.funding?.funded === false
                        ? <span className="badge b-bad">✕ {t("gap {g}", { g: money(m.funding.gap_minor, tl.data.currency, { compact: true }) })}</span>
                        : <span className="badge b-neutral">• {t("unknown")}</span>}
                    </td>
                    <td className="n">{m.budget ? money(m.budget.remaining_minor, tl.data.currency, { compact: true }) : <span className="muted">{t("no budget")}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="tiny muted" style={{ marginTop: 6 }}>{t("Funded = projected month-end cash (all programs, commitments, confirmed flows) stays above the minimum reserve through the milestone's planned end.")}</div>
        </div>
        <div className="card">
          <div className="card-head">
            <h2>{t("Projected cash")}</h2>
            <Link to="/budget" className="small">{t("Budget and runway →")}</Link>
          </div>
          {fc.start_cash_minor == null ? (
            <Empty title={t("Cash balance incomplete")}>{t("Add a reconciled balance for each account in Budget and Runway → Cash and FX.")}</Empty>
          ) : (
            <CashForecastChart months={fc.months} reserve={fc.reserve_minor} ccy={ccy} />
          )}
          <ChartMeta rows={[[t("Metric"), t("Month-end projected cash, {c}", { c: ccy })], [t("Basis"), t("Reconciled cash + approved/planned budget schedules + open commitments + confirmed flows")], [t("Data"), t("Internal records (see provenance on each page)")]]} />
        </div>
      </div>

      <div>
        <div className="card">
          <div className="card-head">
            <h2>{t("Recent external developments")}</h2>
            <Link to="/competitors" className="small">{t("Competitor intelligence →")}</Link>
          </div>
          {ev.loading && <Loading />}
          {ev.data && ev.data.events.length === 0 && <Empty title={t("No events captured yet")}>{t("Run a competitor refresh for a confirmed program.")}</Empty>}
          {ev.data?.events.slice(0, 5).map((e: Json) => (
            <div key={e.id} style={{ marginBottom: 8 }}>
              <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{e.title}</div>
              <div className="row">
                <Prov kind={e.origin === "fixture" ? "fixture" : "external"} /> <span className="small muted">{e.program_code} · {t("relevance {n}", { n: e.relevance })}</span>
              </div>
              <Source url={e.source_url} name={e.source_name} published={e.published_at} retrieved={e.retrieved_at} />
            </div>
          ))}
          {ev.data && <div className="freshness">{t("Last check: {a}", { a: ago(ev.data.last_check, lang) })}</div>}
          {acts.data && acts.data.length > 0 && (
            <div className="alert info">
              <span>i</span>
              <span>
                {t("{n} AI-proposed action(s) await review in the", { n: acts.data.length })} <Link to="/competitors">{t("action queue")}</Link>.
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
