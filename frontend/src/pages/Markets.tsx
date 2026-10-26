import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, waitForJob, type Json } from "../api";
import { ChartMeta, RevenueChart, ShareDonut } from "../components/charts";
import { Badge, Empty, ErrorBox, Loading, PageHead, Prov, StatusPill, useApi } from "../components/ui";
import { dateOnly } from "../format";
import { useI18n } from "../i18n";

const CRITERIA = ["therapeutic_species_fit", "portfolio_relevance", "geographic_capability", "commercial_capability", "prior_licensing_activity", "stated_strategic_interest"];

export default function Markets() {
  const { t, tl, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const program = sp.get("program") || "";
  const progs = useApi("/api/programs");
  const m = useApi("/api/markets");
  const pr = useApi(`/api/partners${program ? `?program_id=${program}` : ""}`);
  const [geo, setGeo] = useState("");
  const [vt, setVt] = useState("");
  const [job, setJob] = useState<Json>(null);
  const [url, setUrl] = useState<Json>({ url: "", company: "", criterion: "stated_strategic_interest" });
  const [urlRes, setUrlRes] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const runJob = async (path: string, after: () => void) => {
    setErr(null);
    try {
      const j = await api.post(path);
      setJob({ status: "running", id: j.job_id });
      setJob(await waitForJob(j.job_id, setJob));
      after();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const obs: Json[] = (m.data?.observations || []).filter((o: Json) => (!geo || o.geography === geo) && (!vt || o.value_type === vt));
  const revenue = obs.filter((o) => o.metric === "revenue");
  const defs = Array.from(new Set(revenue.map((o) => o.market_definition)));
  const prog = (progs.data || []).find((p: Json) => String(p.id) === program);
  const zh = lang === "zh";
  return (
    <div>
      <PageHead title={t("Markets and Licensing")} question={t("How big are the animal-health players, and who could license our products?")}
        next={[["/competitors", t("Competitor Intelligence")], ["/pipelines", t("Pipelines")]]}>
        <button onClick={() => runJob("/api/markets/refresh", m.reload)}>{t("Refresh market data")}</button>
        {job && <StatusPill status={job.status} />}
      </PageHead>
      <div className="tiny muted" style={{ marginTop: -10, marginBottom: 10 }}>{t("Sourced market observations and evidence-based potential partners. No inferred market shares, deal values, or contacts.")}</div>
      {err && <ErrorBox error={err} />}
      <div className="card">
        <div className="pill-filter">
          <label className="f">{t("Geography")}<select value={geo} onChange={(e) => setGeo(e.target.value)}><option value="">{t("All")}</option>{Array.from(new Set((m.data?.observations || []).map((o: Json) => o.geography))).map((g) => <option key={g as string}>{g as string}</option>)}</select></label>
          <label className="f">{t("Value type")}<select value={vt} onChange={(e) => setVt(e.target.value)}><option value="">{t("All")}</option>{["reported", "estimated", "sample"].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select></label>
          <span className="small muted">{t("Indication/species filters apply when observations at that level exist; current sources report company totals only.")}</span>
        </div>
        {m.loading && <Loading />}
        {revenue.length === 0 && !m.loading && <Empty title={t("No market observations")}>{t("Refresh market data (live mode retrieves reported revenue from SEC XBRL filings).")}</Empty>}
        {defs.map((d) => {
          const rows = revenue.filter((o) => o.market_definition === d);
          const sample = rows.some((o) => o.value_type === "sample");
          return (
            <div key={d as string}>
              <h2>{t("Comparable reported revenue")} {sample && <Prov kind="synthetic" />}</h2>
              <RevenueChart rows={rows} />
              <ChartMeta rows={[
                [t("Definition"), zh ? t("公司报告的总收入（动物保健公司）") : (d as string)], [t("Geography"), rows[0].geography], [t("Period"), t("Each company's fiscal year (end dates differ)")], [t("Metric"), `${tl(rows[0].metric)}, ${rows[0].currency || ""}`],
                [t("Value type"), Array.from(new Set(rows.map((o) => tl(o.value_type)))).join(", ")], [t("Source"), Array.from(new Set(rows.map((o) => o.source_name.split(" (")[0]))).join("; ") + ` · ${t("retrieved")} ${dateOnly(rows[0].retrieved_at)}`],
                [t("Coverage"), rows[0].coverage_note], [t("Not shown"), t("Market share: no comparable share dataset with a common market definition. Private companies (e.g. Boehringer Ingelheim, Ceva) and segment-level animal-health revenue of diversified companies (e.g. Merck) are not included.")],
              ]} />
            </div>
          );
        })}
        {(m.data?.share_datasets || []).filter((s: Json) => s.rows.length <= 4).map((s: Json) => (
          <div key={s.definition}><h2>{t("Market share: {d}", { d: s.definition })}</h2><ShareDonut rows={s.rows} /><ChartMeta rows={[[t("Geography"), s.geography], [t("Period"), s.period]]} /></div>
        ))}
        <div className="tiny muted">{t("A donut/pie chart is drawn only when market-share rows share the same market definition, geography, period and source basis. Otherwise a sourced revenue comparison is shown.")} {t("Company revenue is not market share. Totals cover all species and products of each company.")}</div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>{t("Potential license-out partners")}</h2>
          <div className="row">
            <label className="f">{t("Program")}<select value={program} onChange={(e) => setSp(e.target.value ? { program: e.target.value } : {})}><option value="">{t("All")}</option>{(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}</select></label>
            <button className="primary" disabled={!program || !prog?.profile_confirmed_at} onClick={() => runJob(`/api/programs/${program}/research/partners`, pr.reload)}>{t("Assess partners")}</button>
          </div>
        </div>
        <div className="alert info"><span>i</span><span>{t("Potential partners based on public evidence. Not confirmed interest, deal terms, or contacts.")} {t("Fit score = sum of criterion weights for criteria with at least one cited public source (species fit 25, portfolio 20, geography 15, commercial 15, licensing history 15, stated interest 10). It measures documented evidence, not likelihood of a deal.")}</span></div>
        {pr.loading && <Loading />}
        {pr.data && pr.data.partners.length === 0 && <Empty title={t("No partner assessment yet")}>{t("Choose a confirmed program and run “Assess partners”.")}</Empty>}
        {pr.data?.partners.map((p: Json) => (
          <article key={p.id} className="event">
            <div className="row">
              <h3 style={{ margin: 0 }}>{p.company}</h3>
              <Badge tone={p.fit_score >= 60 ? "good" : p.fit_score >= 30 ? "warn" : "neutral"}>{t("documented fit {n}/100", { n: p.fit_score })}</Badge>
              <span className="small muted">{p.program_code}</span>
              <span className="spacer" />
              <Prov kind={p.origin === "fixture" ? "fixture" : "agent"} />
            </div>
            <div className="row small" style={{ margin: "6px 0" }}>
              {CRITERIA.map((c) => <Badge key={c} tone={p.criteria?.[c] ? "good" : "neutral"}>{p.criteria?.[c] ? "✓" : "—"} {tl(c)}</Badge>)}
            </div>
            <div className="section-label">{t("Evidence (factual, from public sources)")}</div>
            {p.evidence.length === 0 ? <div className="small muted">{t("No supporting public evidence found.")}</div> : p.evidence.map((e: Json, i: number) => (
              <div key={i} className="small" style={{ marginBottom: 3 }}>
                <Badge>{tl(e.criterion)}</Badge> {e.fact} — <a href={e.source_url} target="_blank" rel="noopener noreferrer nofollow">{e.source_name} ↗</a> {e.user_supplied && <Badge>{t("user-supplied")}</Badge>} <span className="tiny muted">{t("retrieved")} {dateOnly(e.retrieved_at)}</span>
              </div>
            ))}
            {p.ai_assessment && <div style={{ marginTop: 6 }}><Prov kind="ai" /> <span className="small">{p.ai_assessment}</span></div>}
            {p.gaps.length > 0 && <div className="tiny muted" style={{ marginTop: 4 }}>{t("Evidence gaps:")} {p.gaps.join("; ")}</div>}
          </article>
        ))}
      </div>

      <div className="card">
        <h2>{t("Research a public URL (no paid search needed)")}</h2>
        <div className="small muted">{t("Paste a public page (e.g., a company press release). It is fetched safely (no private networks, size and time limits), treated as untrusted text, and can be attached as partner evidence.")}</div>
        <div className="form-grid" style={{ marginTop: 8 }}>
          <label className="f">{t("Public URL")}<input value={url.url} onChange={(e) => setUrl({ ...url, url: e.target.value })} placeholder="https://" /></label>
          <label className="f">{t("Attach to company (optional)")}<input value={url.company} onChange={(e) => setUrl({ ...url, company: e.target.value })} /></label>
          <label className="f">{t("Criterion")}<select value={url.criterion} onChange={(e) => setUrl({ ...url, criterion: e.target.value })}>{CRITERIA.map((c) => <option key={c} value={c}>{tl(c)}</option>)}</select></label>
        </div>
        <button style={{ marginTop: 8 }} disabled={!program || !url.url} onClick={async () => {
          setErr(null);
          try {
            const qs = url.company ? `?company=${encodeURIComponent(url.company)}&criterion=${url.criterion}` : "";
            setUrlRes(await api.post(`/api/research/url${qs}`, { url: url.url, program_id: Number(program) }));
            pr.reload();
          } catch (e: Json) {
            setErr(e.message);
          }
        }}>{t("Fetch and review")}</button>
        {!program && <span className="small muted"> {t("Choose a program above first.")}</span>}
        {urlRes && (
          <div className="event" style={{ marginTop: 8 }}>
            <Prov kind="external" /> <b>{urlRes.title}</b> <a href={urlRes.final_url} target="_blank" rel="noopener noreferrer nofollow">{t("open ↗")}</a>
            <div className="tiny muted">{t("retrieved {r} · sha256 {h} · untrusted text, shown as data", { r: urlRes.retrieved_at, h: urlRes.sha256.slice(0, 12) })}</div>
            <div className="small" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{urlRes.excerpt}</div>
          </div>
        )}
      </div>
    </div>
  );
}
