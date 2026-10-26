import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, waitForJob, type Json } from "../api";
import { Badge, Empty, ErrorBox, Loading, PageHead, Prov, Source, StatusPill, Tabs, useApi } from "../components/ui";
import { ago, dateOnly } from "../format";
import { useI18n } from "../i18n";

export default function Competitors() {
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const program = sp.get("program") || "";
  const [tab, setTab] = useState("pipelines");
  const progs = useApi("/api/programs");
  return (
    <div>
      <PageHead title={t("Competitor Intelligence")} question={t("What are other companies doing that could affect our programs?")}
        next={[["/briefing", t("Daily Briefing")], ["/regulatory", t("Regulatory Intelligence")]]}>
        <label className="f">{t("Program")}
          <select value={program} onChange={(e) => setSp(e.target.value ? { program: e.target.value } : {})}>
            <option value="">{t("All programs")}</option>
            {(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}
          </select>
        </label>
      </PageHead>
      <Tabs value={tab} onChange={setTab} tabs={[
        ["pipelines", t("Competitors by pipeline"), t("Start here: who competes with each pipeline, their product, and their latest move.")],
        ["events", t("All news"), t("Public events found for each program: what the source says, what it may mean, and what to review.")],
        ["actions", t("Follow-ups"), t("Follow-ups proposed by the AI or added by the team. Only people accept or close them.")],
        ["competitors", t("Add or manage competitors"), t("Companies we watch, and AI-suggested ones to track or dismiss.")],
      ]} />
      {tab === "pipelines" && <ByPipeline onOpen={(pid) => { setSp({ program: String(pid) }); setTab("events"); }} />}
      {tab === "events" && <Events program={program} programs={progs.data || []} />}
      {tab === "competitors" && <CompetitorList program={program} programs={progs.data || []} />}
      {tab === "actions" && <ActionQueue program={program} />}
    </div>
  );
}

function ByPipeline({ onOpen }: { onOpen: (pid: number) => void }) {
  const { t, tl } = useI18n();
  const { data, error, reload } = useApi("/api/competitors/by-pipeline");
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  return (
    <div>
      {data.map((p: Json) => (
        <div key={p.program_id} className="card comp-pipe">
          <div className="card-head">
            <h2 style={{ margin: 0 }}>{p.code} <span className="small muted" style={{ fontWeight: 400 }}>{p.name}</span> {p.status !== "active" && <Badge>{tl(p.status)}</Badge>}</h2>
            <button className="link small" onClick={() => onOpen(p.program_id)}>{t("All news for {c} →", { c: p.code })}</button>
          </div>
          {p.competitors.length === 0 ? (
            <div className="small muted">{t("No competitors tracked yet. Add one under \"Add or manage competitors\", or refresh research for this pipeline.")}</div>
          ) : p.competitors.map((c: Json) => (
            <div key={c.id} className="comp-row">
              <div><div className="lbl">{t("Competitor")}</div><b>{c.company}</b> {c.status === "suggested" && <Badge tone="warn">{t("AI-suggested")}</Badge>}</div>
              <div><div className="lbl">{t("Product")}</div>{c.product || "—"}{c.stage && <div className="tiny muted">{c.stage}</div>}</div>
              <div>
                <div className="lbl">{t("Latest movement")}</div>
                {c.latest ? (
                  <>
                    <div><Badge>{tl(c.latest.event_type)}</Badge> <b className="small">{c.latest.title}</b></div>
                    {c.latest.observed && <div className="small">{c.latest.observed}</div>}
                    <Source url={c.latest.source_url} name={c.latest.source_name} published={c.latest.published_at} retrieved={c.latest.first_seen_at} />
                  </>
                ) : <span className="small muted">{t("No movement captured yet. Refresh research to check public sources.")}</span>}
              </div>
            </div>
          ))}
          {p.unlinked_events.length > 0 && (
            <div className="comp-news">
              <div className="lbl">{t("Latest related news (not tied to a named competitor)")}</div>
              {p.unlinked_events.slice(0, 2).map((e: Json) => (
                <div key={e.id} className="small" style={{ marginTop: 4 }}>
                  <Badge>{tl(e.event_type)}</Badge> <b>{e.title}</b>
                  <div><Source url={e.source_url} name={e.source_name} published={e.published_at} retrieved={e.first_seen_at} /></div>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="tiny muted">{t("Only public sources this app searched are shown; this is not a complete record of competitor activity.")}</div>
    </div>
  );
}

function Events({ program, programs }: { program: string; programs: Json[] }) {
  const { t, tl, lang } = useI18n();
  const [dups, setDups] = useState(false);
  const { data, error, loading, reload } = useApi(`/api/events?days=365${program ? `&program_id=${program}` : ""}${dups ? "&include_duplicates=true" : ""}`);
  const [job, setJob] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const refresh = async () => {
    if (!program) return;
    setErr(null);
    try {
      const j = await api.post(`/api/programs/${program}/research/competitors`);
      setJob({ status: "running", id: j.job_id });
      const f = await waitForJob(j.job_id, setJob);
      setJob(f);
      reload();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const prog = programs.find((p) => String(p.id) === program);
  return (
    <div>
      <div className="card row">
        <button className="primary" disabled={!program || !prog?.profile_confirmed_at || job?.status === "running"} onClick={refresh}>{t("Refresh now")}</button>
        {job?.status === "running" && <button className="danger" onClick={() => api.post(`/api/jobs/${job.id}/cancel`)}>{t("Cancel")}</button>}
        {!program && <span className="small muted">{t("Choose a program to run a refresh.")}</span>}
        {prog && !prog.profile_confirmed_at && <span className="small" style={{ color: "var(--warn)" }}>! {t("Confirm this program's profile first.")}</span>}
        {job && <span className="small"><StatusPill status={job.status} /> {job.error} {job.result?.counts && Object.entries(job.result.counts).map(([k, v]) => `${tl(k)} ${v}`).join(" · ")}</span>}
        <span className="spacer" />
        <label className="row small"><input type="checkbox" checked={dups} onChange={(e) => setDups(e.target.checked)} /> {t("show duplicates")}</label>
        {data && <span className="freshness">{t("Last successful check {a}", { a: ago(data.last_check, lang) })}</span>}
      </div>
      {err && <ErrorBox error={err} />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading />}
      {data && (
        <>
          <div className="alert info"><span>i</span><span>{t("Events come only from the sources this app searched (listed in each run's trace). This is not a complete record of competitor activity, and the app does not know confidential plans.")} {data.duplicates_hidden ? t("{n} duplicate report(s) hidden.", { n: data.duplicates_hidden }) : ""}</span></div>
          {data.events.length === 0 && <Empty title={t("No events captured")}>{t("Run a refresh. Live mode searches Europe PMC, ClinicalTrials.gov, SEC EDGAR full-text and veterinary/biotech news feeds using only the confirmed public profile.")}</Empty>}
          {data.events.map((e: Json) => (
            <article key={e.id} className="event">
              <div className="row">
                <Badge>{tl(e.event_type)}</Badge>
                {e.new_since_last_check && <Badge tone="good">{t("new since last check")}</Badge>}
                {e.change_note && <Badge tone="warn">! {e.change_note}</Badge>}
                {e.duplicate_of && <Badge>{t("duplicate of #{n}", { n: e.duplicate_of })}</Badge>}
                <span className="small muted">{e.program_code} · {t("relevance {n}/100", { n: e.relevance })} {e.competitor && `· ${e.competitor}`}</span>
                <span className="spacer" />
                {e.origin === "fixture" && <Prov kind="fixture" />}
              </div>
              <h3 style={{ margin: "6px 0 2px" }}>{e.title}</h3>
              <Source url={e.source_url} name={e.source_name} published={e.published_at} retrieved={e.retrieved_at} />
              <dl className="layer">
                <dt><Prov kind={e.origin === "fixture" ? "fixture" : "external"} /> {t("Observed")}</dt><dd>{e.observed}</dd>
                {e.interpretation && <><dt><Prov kind="ai" /> {t("Interpretation")}</dt><dd>{e.interpretation}</dd></>}
                {e.possible_next_move && <><dt><Prov kind="hypothesis" /> {t("Possible next move")}</dt><dd>{e.possible_next_move}</dd></>}
                {e.suggested_action && <><dt><Prov kind="ai" /> {t("Suggested action")}</dt><dd>{e.suggested_action} <span className="tiny muted">{t("(see action queue)")}</span></dd></>}
                <dt>{t("Why relevant")}</dt><dd className="small muted">{e.relevance_reason}</dd>
              </dl>
              <div className="tiny muted" style={{ marginTop: 4 }}>{t("First seen {a} · last seen {b}", { a: dateOnly(e.first_seen_at), b: dateOnly(e.last_seen_at) })}</div>
              {lang === "zh" && <div className="tiny muted">{t("Research text is shown in its original language.")}</div>}
            </article>
          ))}
        </>
      )}
    </div>
  );
}

function CompetitorList({ program, programs }: { program: string; programs: Json[] }) {
  const { t } = useI18n();
  const { data, reload } = useApi(`/api/competitors${program ? `?program_id=${program}` : ""}`);
  const blank = { company: "", product: "", species: "", indication: "", mechanism: "", modality: "", geography: "", stage: "", source_url: "" };
  const [f, setF] = useState<Json>(blank);
  const [err, setErr] = useState<string | null>(null);
  const add = async () => {
    try {
      await api.post("/api/competitors", { ...f, program_id: program ? Number(program) : null, species: f.species.split(",").map((s: string) => s.trim()).filter(Boolean), source_url: f.source_url || null });
      setF(blank);
      reload();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const setStatus = async (id: number, status: string) => {
    await api.post(`/api/competitors/${id}/status?status=${status}`);
    reload();
  };
  return (
    <div>
      <div className="card">
        {!data ? <Loading /> : data.length === 0 ? <Empty title={t("No competitors yet")}>{t("Add competitors manually, or review AI-suggested matches after a refresh.")}</Empty> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>{t("Company / product")}</th><th>{t("Program")}</th><th>{t("Species · indication")}</th><th>{t("Mechanism · modality")}</th><th>{t("Geography · stage")}</th><th>{t("Status")}</th><th>{t("Basis")}</th><th className="n">{t("Events")}</th><th /></tr></thead>
              <tbody>{data.map((c: Json) => (
                <tr key={c.id}>
                  <td><b>{c.company}</b><div className="small">{c.product || "—"}</div></td>
                  <td>{c.program_code || t("all")}</td>
                  <td className="small">{c.species.join(", ") || "—"} · {c.indication || "—"}</td>
                  <td className="small">{c.mechanism || "—"} · {c.modality || "—"}</td>
                  <td className="small">{c.geography || "—"} · {c.stage || "—"}</td>
                  <td><StatusPill status={c.status} /></td>
                  <td className="small" style={{ maxWidth: 260 }}><Prov kind={c.origin === "agent" ? "ai" : c.origin} /> {c.match_reason}{c.source_url && <div><a href={c.source_url} target="_blank" rel="noopener noreferrer nofollow">{t("source ↗")}</a></div>}</td>
                  <td className="n">{c.event_count}</td>
                  <td>
                    {c.status === "suggested" && <div className="row"><button className="link small" onClick={() => setStatus(c.id, "tracked")}>{t("Track")}</button><button className="link small" onClick={() => setStatus(c.id, "dismissed")}>{t("Dismiss")}</button></div>}
                    {c.status === "tracked" && <button className="link small" onClick={() => setStatus(c.id, "dismissed")}>{t("Stop tracking")}</button>}
                  </td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        <h3>{t("Add a competitor manually")} {program && `(${programs.find((p) => String(p.id) === program)?.code})`}</h3>
        <div className="form-grid">
          {[["company", "Company"], ["product", "Product"], ["species", "Species (comma-separated)"], ["indication", "Indication"], ["mechanism", "Mechanism"], ["modality", "Modality"], ["geography", "Geography"], ["stage", "Stage"], ["source_url", "Source URL"]].map(([k, n]) => (
            <label key={k} className="f">{t(n)}<input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
          ))}
        </div>
        {err && <ErrorBox error={err} />}
        <button style={{ marginTop: 8 }} disabled={!f.company} onClick={add}>{t("Add competitor")}</button>
      </div>
    </div>
  );
}

export function ActionQueue({ program }: { program: string }) {
  const { t, tl } = useI18n();
  const { data, reload } = useApi(`/api/actions${program ? `?program_id=${program}` : ""}`);
  const [f, setF] = useState<Json>({ title: "", owner: "", priority: "medium", due_date: "" });
  const upd = async (id: number, body: Json) => {
    await api.patch(`/api/actions/${id}`, body);
    reload();
  };
  return (
    <div className="card">
      <div className="tiny muted" style={{ marginBottom: 8 }}>{t("Agents may propose actions; only people accept, assign, and close them. Accepting an action never changes budgets or milestones.")}</div>
      {!data ? <Loading /> : data.length === 0 ? <Empty title={t("No actions")} /> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>{t("Action")}</th><th>{t("Program")}</th><th>{t("Origin")}</th><th>{t("Owner")}</th><th>{t("Priority")}</th><th>{t("Due")}</th><th>{t("Status")}</th><th /></tr></thead>
            <tbody>{data.map((a: Json) => (
              <tr key={a.id}>
                <td style={{ maxWidth: 360 }}>{a.title}<div className="tiny muted">{a.detail}</div></td>
                <td>{a.program_code || "—"}</td>
                <td>{a.created_by === "agent" ? <Prov kind="ai" /> : <Prov kind={a.origin} />}</td>
                <td><input defaultValue={a.owner || ""} onBlur={(e) => e.target.value !== (a.owner || "") && upd(a.id, { owner: e.target.value })} aria-label={t("Owner")} style={{ width: 120 }} /></td>
                <td><select value={a.priority} onChange={(e) => upd(a.id, { priority: e.target.value })} aria-label={t("Priority")}>{["high", "medium", "low"].map((p) => <option key={p} value={p}>{tl(p)}</option>)}</select></td>
                <td><input type="date" defaultValue={a.due_date || ""} onChange={(e) => upd(a.id, { due_date: e.target.value || null })} aria-label={t("Due date")} /></td>
                <td><StatusPill status={a.status} /></td>
                <td className="row">
                  {a.status === "proposed" && <button className="link small" onClick={() => upd(a.id, { status: "open" })}>{t("Accept")}</button>}
                  {a.status !== "done" && <button className="link small" onClick={() => upd(a.id, { status: "done" })}>{t("Done")}</button>}
                  {a.status !== "dismissed" && <button className="link small" onClick={() => upd(a.id, { status: "dismissed" })}>{t("Dismiss")}</button>}
                </td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <div className="form-grid" style={{ marginTop: 10 }}>
        <label className="f">{t("New action")}<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        <label className="f">{t("Owner")}<input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} /></label>
        <label className="f">{t("Priority")}<select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>{["high", "medium", "low"].map((p) => <option key={p} value={p}>{tl(p)}</option>)}</select></label>
        <label className="f">{t("Due")}<input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></label>
      </div>
      <button style={{ marginTop: 8 }} disabled={!f.title} onClick={async () => { await api.post("/api/actions", { ...f, due_date: f.due_date || null, program_id: program ? Number(program) : null }); setF({ title: "", owner: "", priority: "medium", due_date: "" }); reload(); }}>{t("Add action")}</button>
    </div>
  );
}
