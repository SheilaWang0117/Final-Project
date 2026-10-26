import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, waitForJob, type Json } from "../api";
import { Badge, Empty, ErrorBox, Loading, PageHead, Prov, Source, StatusPill, Tabs, useApi } from "../components/ui";
import { ago } from "../format";
import { useI18n } from "../i18n";

export default function Regulatory() {
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const program = sp.get("program") || "";
  const [tab, setTab] = useState("documents");
  const progs = useApi("/api/programs");
  return (
    <div>
      <PageHead title={t("Regulatory Intelligence")} question={t("Which official guidance could apply to our programs, and what must a specialist confirm?")}
        next={[["/pipelines", t("Pipelines")], ["/briefing", t("Daily Briefing")]]}>
        <label className="f">{t("Program")}
          <select value={program} onChange={(e) => setSp(e.target.value ? { program: e.target.value } : {})}>
            <option value="">{t("All programs")}</option>
            {(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}
          </select>
        </label>
      </PageHead>
      <div className="tiny muted" style={{ marginTop: -10, marginBottom: 10 }}>{t("Research summaries mapped to your confirmed profile — not regulatory determinations. Specialist confirmation is required.")}</div>
      <Tabs value={tab} onChange={setTab} tabs={[
        ["documents", t("Documents and applicability"), t("Official documents found for each program, with status, quotes and open questions.")],
        ["coverage", t("Authorities and coverage"), t("Which regulator is responsible in each region, which sources were checked, and gaps.")],
      ]} />
      {tab === "documents" && <Docs program={program} programs={progs.data || []} />}
      {tab === "coverage" && <Coverage />}
    </div>
  );
}

function Docs({ program, programs }: { program: string; programs: Json[] }) {
  const { t, tl, lang } = useI18n();
  const { data, error, loading, reload } = useApi(`/api/regulatory/documents${program ? `?program_id=${program}` : ""}`);
  const tlData = useApi("/api/timeline");
  const [job, setJob] = useState<Json>(null);
  const prog = programs.find((p) => String(p.id) === program);
  const refresh = async () => {
    const j = await api.post(`/api/programs/${program}/research/regulatory`);
    setJob({ status: "running", id: j.job_id });
    setJob(await waitForJob(j.job_id, setJob));
    reload();
  };
  const ms = (id: number) => (tlData.data?.milestones || []).find((m: Json) => m.id === id);
  return (
    <div>
      <div className="card row">
        <button className="primary" disabled={!program || !prog?.profile_confirmed_at || job?.status === "running"} onClick={refresh}>{t("Refresh regulatory research")}</button>
        {!program && <span className="small muted">{t("Choose a program.")}</span>}
        {prog && <span className="small muted">{t("Scope: {u} · {m} · {j}", { u: tl(prog.use_type), m: tl(prog.molecule_category), j: prog.jurisdictions.join(", ") || t("all five regions") })}</span>}
        {job && <span className="small"><StatusPill status={job.status} /> {job.error} {job.result?.counts && Object.entries(job.result.counts).map(([k, v]) => `${tl(k)} ${v}`).join(" · ")}</span>}
      </div>
      {job?.result?.plan && (
        <div className="alert info"><span>i</span><span>{t("Searched {j} for {s}. Not searched: {n}. Manual-only sources: {m}.", { j: job.result.plan.jurisdictions.join(", "), s: job.result.plan.scopes.map((s: string) => tl(s)).join(", "), n: job.result.plan.not_searched.join(", ") || t("none"), m: job.result.plan.manual_only.map((m: Json) => m.authority).join("; ") || t("none") })}</span></div>
      )}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading />}
      {data && data.length === 0 && <Empty title={t("No documents assessed yet")}>{t("Confirm a profile, then refresh. “Latest” means latest verified within the documented search scope.")}</Empty>}
      {lang === "zh" && data && data.length > 0 && <div className="tiny muted" style={{ marginBottom: 6 }}>{t("Research text is shown in its original language.")}</div>}
      {data?.map((d: Json) => (
        <article key={`${d.id}-${d.program_id}`} className="event">
          <div className="row">
            <Badge>{d.jurisdiction}</Badge>
            <Badge tone={d.doc_status === "final" ? "good" : d.doc_status === "draft" ? "warn" : "neutral"}>{tl(d.doc_status)}</Badge>
            <Badge tone={d.binding === "binding" ? "bad" : "neutral"}>{d.binding === "binding" ? t("binding regulation") : d.binding === "guidance" ? t("guidance (non-binding)") : t("binding status unknown")}</Badge>
            {d.version > 1 && <Badge tone="warn">! {t("changed {d} (v{v})", { d: d.changed_at?.slice(0, 10), v: d.version })}</Badge>}
            <span className="small muted">{t("relevance {n}/100", { n: d.relevance })}</span>
            <span className="spacer" />
            {d.origin === "fixture" ? <Prov kind="fixture" /> : <Prov kind="external" />}
            <StatusPill status={d.review_status || "needs_review"} />
          </div>
          <h3 style={{ margin: "6px 0 2px" }}>{d.title}</h3>
          {d.original_title && d.original_title !== d.title && <div className="small">{t("Original title:")} <span lang={d.language}>{d.original_title}</span></div>}
          <div className="small muted">{d.authority}</div>
          <Source url={d.url} published={d.published_date} retrieved={d.retrieved_at} />
          <dl className="layer">
            <dt><Prov kind="ai" /> {t("Summary")}{d.is_translation ? ` ${t("(AI translation)")}` : ""}</dt><dd>{d.summary_en}</dd>
            <dt><Prov kind="ai" /> {t("Applicability")}</dt><dd>{d.applicability}</dd>
            {d.passages.length > 0 && <><dt><Prov kind="external" /> {t("Verbatim passages")}</dt><dd>{d.passages.map((p: Json, i: number) => <div key={i} className="quote" lang={d.language}>“{p.text}” {p.section && <span className="tiny muted">— {p.section}</span>}</div>)}<div className="tiny muted">{t("Passages are kept only if they appear verbatim in the retrieved text.")}</div></dd></>}
            {d.unresolved.length > 0 && <><dt>{t("Needs specialist confirmation")}</dt><dd><ul style={{ margin: 0, paddingLeft: 18 }}>{d.unresolved.map((q: string) => <li key={q}>{q}</li>)}</ul></dd></>}
            {d.affected_milestones.length > 0 && <><dt>{t("Flagged milestones")}</dt><dd>{d.affected_milestones.map((id: number) => ms(id)?.name || `#${id}`).join(", ")} <span className="tiny muted">{t("(flagged for review; plans unchanged)")}</span></dd></>}
          </dl>
          {d.assessment_id && (
            <div className="row" style={{ marginTop: 6 }}>
              <button className="small" onClick={async () => { await api.post(`/api/regulatory/assessments/${d.assessment_id}/review?status=reviewed`); reload(); }}>{t("Mark reviewed")}</button>
              <button className="small" onClick={async () => { await api.post(`/api/regulatory/assessments/${d.assessment_id}/review?status=not_applicable`); reload(); }}>{t("Not applicable")}</button>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function Coverage() {
  const { t, tl, lang } = useI18n();
  const { data, loading } = useApi("/api/regulatory/sources");
  if (loading || !data) return <Loading />;
  const jurs = Array.from(new Set(data.map((s: Json) => s.jurisdiction))) as string[];
  const names: Record<string, string> = { US: t("United States"), EU: t("European Union"), CN: t("China"), JP: t("Japan"), KR: t("South Korea") };
  return (
    <div>
      <div className="alert warning"><span>!</span><span>{t("Authority mapping is curated and must be confirmed per product. For example, US veterinary antibodies may fall under FDA CVM or USDA CVB depending on mechanism and claims; China veterinary products fall under MARA, not NMPA.")}</span></div>
      {jurs.map((j) => (
        <div className="card" key={j}>
          <h2>{names[j] || j}</h2>
          <table className="t">
            <thead><tr><th>{t("Product type")}</th><th>{t("Responsible authority")}</th><th>{t("Source")}</th><th>{t("Access")}</th><th>{t("Last successful check")}</th><th>{t("Last status")}</th></tr></thead>
            <tbody>{data.filter((s: Json) => s.jurisdiction === j).map((s: Json) => (
              <tr key={s.id}>
                <td>{tl(s.scope)}</td>
                <td className="small" style={{ maxWidth: 320 }}>{s.authority}<div className="tiny muted">{s.notes}</div></td>
                <td className="small"><a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.name} ↗</a> <Badge>{s.language}</Badge></td>
                <td><Badge tone={s.access === "manual_only" ? "warn" : "neutral"}>{tl(s.access)}</Badge></td>
                <td className="small">{s.last_success_at ? ago(s.last_success_at, lang) : t("never")}</td>
                <td>{s.last_status ? <StatusPill status={s.last_status === "ok" ? "succeeded" : "failed"} /> : "—"}{s.last_error && <div className="tiny" style={{ color: "var(--bad)" }}>{s.last_error}</div>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
