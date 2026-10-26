import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, waitForJob, type Json } from "../api";
import { useStatus } from "../App";
import { Paw } from "../components/pets";
import { Badge, Empty, ErrorBox, Loading, Modal, PageHead, Prov, RunTrace, StatusPill, useApi } from "../components/ui";
import { dateOnly, money } from "../format";
import { useI18n } from "../i18n";

const FIELDS: [string, string][] = [
  ["use_type", "Human or veterinary"], ["species", "Target species"], ["therapeutic_area", "Therapeutic area"], ["indication", "Indication"],
  ["modality", "Modality"], ["molecule_category", "Molecule category"], ["target", "Target"], ["mechanism", "Mechanism of action"],
  ["route", "Route of administration"], ["jurisdictions", "Target jurisdictions"],
];
const STATUS_TONE: Record<string, "good" | "warn" | "neutral"> = { stated: "good", inferred: "warn", unknown: "neutral" };

// ------------------------------------------------------------------- list

export default function Pipelines() {
  const { t, tl } = useI18n();
  const [q, setQ] = useState("");
  const [use, setUse] = useState("");
  const [status, setStatus] = useState("");
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (use) params.set("use_type", use);
  if (status) params.set("status", status);
  if (archived) params.set("include_archived", "true");
  const { data, error, loading, reload } = useApi(`/api/programs?${params}`);
  const tlData = useApi("/api/timeline");
  return (
    <div>
      <PageHead title={t("Pipelines")} question={t("What are we developing, and what has to happen next?")}
        next={[["/budget", t("Budget and Runway")], ["/regulatory", t("Regulatory Intelligence")]]}>
        <button className="primary" onClick={() => setCreating(true)}>+ {t("New program")}</button>
      </PageHead>
      <div className="pill-filter card" style={{ padding: 12 }}>
        <label className="f">{t("Search")}<input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("name, code, indication, species")} aria-label={t("Search programs")} /></label>
        <label className="f">{t("Use")}<select value={use} onChange={(e) => setUse(e.target.value)}><option value="">{t("All")}</option><option value="veterinary">{t("Veterinary")}</option><option value="human">{t("Human")}</option><option value="unknown">{t("Unknown")}</option></select></label>
        <label className="f">{t("Status")}<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("All")}</option>{["active", "on_hold", "discontinued", "completed"].map((s) => <option key={s} value={s}>{tl(s)}</option>)}</select></label>
        <label className="row small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> {t("Include archived")}</label>
      </div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading />}
      {data && data.length === 0 && <Empty title={t("No programs match")}>{t("Create a program or change the filters.")}</Empty>}
      {data && data.length > 0 && (
        <div className="card">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>{t("Code")}</th><th>{t("Name")}</th><th>{t("Use / species")}</th><th>{t("Indication")}</th><th>{t("Modality")}</th><th>{t("Stage")}</th><th>{t("Status")}</th><th>{t("Priority")}</th><th>{t("Profile")}</th><th className="n">{t("Milestones")}</th></tr></thead>
              <tbody>
                {data.map((p: Json) => (
                  <tr key={p.id}>
                    <td><Link to={`/pipelines/${p.id}`}>{p.code}</Link></td>
                    <td>{p.name} {p.origin === "synthetic" && <Prov kind="synthetic" />} {p.archived && <Badge>{t("archived")}</Badge>}</td>
                    <td>{tl(p.use_type)} · {p.species.join(", ") || "—"}</td>
                    <td>{p.indication || "—"}</td>
                    <td>{p.modality || "—"}</td>
                    <td className="small">{p.stage ? t(p.stage) : "—"}</td>
                    <td><StatusPill status={p.status} /></td>
                    <td>{tl(p.priority)}</td>
                    <td>{p.profile_confirmed_at ? <StatusPill status="confirmed" /> : <Badge tone="warn">! {t("unconfirmed")}</Badge>}</td>
                    <td className="n">{p.open_milestones}/{p.milestone_count}{p.overdue_milestones ? <span style={{ color: "var(--bad)" }}> · {t("{n} overdue", { n: p.overdue_milestones })}</span> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="tiny muted" style={{ marginTop: 6 }}>{t("Click a program code to see its profile, milestones and funding.")}</div>
        </div>
      )}
      {tlData.data && <PhaseMap timeline={tlData.data.milestones} currency={tlData.data.currency} />}
      {creating && <NewProgram onClose={() => setCreating(false)} onCreated={reload} />}
    </div>
  );
}

// ------------------------------------------------------------- phase map

const GATE_TEXT: Record<string, string> = { passed: "Gate passed", next: "Next decision gate", ready: "Work done, waiting for an earlier gate", ahead: "Gate ahead" };

// Rows = pipelines, columns = development phases; diamonds between phases are value-inflection decision gates.
export function PhaseMap({ timeline, currency, programId }: { timeline: Json[]; currency: string; programId?: number }) {
  const { t, tl } = useI18n();
  const { data, error, reload } = useApi("/api/phase-map");
  const scroller = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const check = () => setOverflows(el.scrollWidth > el.clientWidth + 2);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [data]);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const byId = Object.fromEntries(timeline.map((m) => [m.id, m]));
  const rows = data.rows.filter((r: Json) => !programId || r.program_id === programId);
  const order = data.phases.map((p: Json) => p.key);
  const cols = `minmax(150px, 170px) repeat(${data.phases.length}, minmax(124px, 1fr))`;
  return (
    <div className="card">
      <div className="card-head">
        <h2>{t("Development phase map")}</h2>
        <div className="legend">
          <span><i className="dot s-done" />{t("Done")}</span>
          <span><i className="dot s-in_progress" />{t("In progress")}</span>
          <span><i className="dot s-planned" />{t("Planned")}</span>
          <span><i className="dot s-at_risk" />{t("At risk / overdue")}</span>
          <span><Paw size={12} color="#00918f" /> {t("Gate passed")}</span>
          <span><i className="gate-key next" />{t("Next decision gate")}</span>
          <span><i className="gate-key ready" />{t("Work done, waiting for an earlier gate")}</span>
          <span><i className="gate-key ahead" />{t("Gate ahead")}</span>
        </div>
      </div>
      <div className="tiny muted" style={{ marginBottom: 8 }}>{t("Each gate is a value-inflection point: a risk is retired, the asset is worth more, and a go / no-go (often financing or partnering) decision belongs there. Gates are passed in order; passed gates leave a paw print.")} {overflows && <span className="ph-scroll-hint">{t("Scroll sideways to see all {n} phases →", { n: data.phases.length })}</span>}</div>
      <div className="phase-scroll" ref={scroller}>
        <div className="phase-grid" style={{ gridTemplateColumns: cols }}>
          <div className="ph-corner"><span>{t("Pipeline")} ↓</span><span>{t("Phase")} →</span></div>
          {data.phases.map((p: Json, i: number) => (
            <div key={p.key} className={`ph-head${p.gate ? " has-gate" : ""}`} title={`${t(p.label)}: ${t(p.detail)}`}>
              <span className="ph-num">{String(i + 1).padStart(2, "0")}</span>
              <span className="ph-name">{t(p.short)}</span>
              {p.gate && <span className="ph-gate-label">◆ {t(p.gate)}</span>}
            </div>
          ))}
          {rows.map((r: Json) => {
            const cur = order.indexOf(r.current_phase);
            return [
              <div key={`${r.code}-label`} className={`ph-row-label${r.status !== "active" ? " muted-row" : ""}`}>
                <Link to={`/pipelines/${r.program_id}`} className="ph-code">{r.code}</Link>
                <span className="tiny muted">{r.name}</span>
                {r.status !== "active" && <Badge>{tl(r.status)}</Badge>}
                <span className="tiny ph-now">{t("Now:")} {t(data.phases[cur].short)}</span>
              </div>,
              ...data.phases.map((p: Json, i: number) => {
                const ms: Json[] = r.cells[p.key] || [];
                const gate = r.gates[p.key];
                return (
                  <div key={`${r.code}-${p.key}`} className={`ph-cell ${i < cur ? "past" : i === cur ? "current" : "future"}${p.gate ? " gate-col" : ""}${r.status !== "active" ? " muted-row" : ""}`}>
                    {ms.map((m) => {
                      const tlm = byId[m.id] || {};
                      const st = tlm.overdue && m.status !== "done" ? "at_risk" : m.status;
                      return (
                        <div key={m.id} className={`ph-chip s-${st}`} title={`${m.name} · ${tl(m.status)} · ${dateOnly(m.planned_start)} → ${dateOnly(m.planned_end)}${m.phase_inferred ? ` · ${t("phase inferred from the name")}` : ""}`}>
                          <div className="ph-chip-name">{m.is_decision_point && <span aria-label={t("decision point")}>◆ </span>}{m.name}</div>
                          <div className="ph-chip-meta">{tl(m.status)} · {dateOnly(m.planned_end)}</div>
                          {tlm.funding?.funded === false && <div className="ph-chip-gap">{t("funding gap {g}", { g: money(tlm.funding.gap_minor, currency, { compact: true }) })}</div>}
                        </div>
                      );
                    })}
                    {gate === "passed" ? (
                      <span className="ph-paw" title={`${t(p.gate)} · ${t(GATE_TEXT[gate])}`} aria-label={`${t(p.gate)}: ${t(GATE_TEXT[gate])}`}><Paw size={13} color="#00918f" /></span>
                    ) : gate ? (
                      <span className={`ph-gate ${gate}`} title={`${t(p.gate)} · ${t(GATE_TEXT[gate])}`} aria-label={`${t(p.gate)}: ${t(GATE_TEXT[gate])}`} />
                    ) : null}
                  </div>
                );
              }),
            ];
          })}
        </div>
      </div>
      <div className="tiny muted" style={{ marginTop: 8 }}>
        {t("A milestone's phase comes from its Stage field; when that is empty it is inferred from the milestone name. CMC and patent work run alongside the studies.")}{" "}
        {t("Sources:")} {data.sources.map((s: Json, i: number) => <span key={s.url}>{i > 0 && " · "}<a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title} ↗</a></span>)}
      </div>
    </div>
  );
}

// ------------------------------------------------------- AI onboarding

function ProposalReview({ proposal, values, setValues }: { proposal: Json; values: Json; setValues: (v: Json) => void }) {
  const { t, tl } = useI18n();
  return (
    <div>
      <div className="table-wrap" style={{ maxHeight: "none" }}>
        <table className="t">
          <thead><tr><th>{t("Field")}</th><th>{t("Proposed value (edit to correct)")}</th><th>{t("Basis")}</th><th>{t("Evidence from your description")}</th></tr></thead>
          <tbody>
            {FIELDS.map(([k, name]) => {
              const f = proposal[k];
              const isList = Array.isArray(f.value);
              return (
                <tr key={k}>
                  <td><b>{t(name)}</b></td>
                  <td>
                    {k === "use_type" ? (
                      <select value={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.value })} aria-label={t(name)}>
                        {["veterinary", "human", "unknown"].map((o) => <option key={o} value={o}>{tl(o)}</option>)}
                      </select>
                    ) : k === "molecule_category" ? (
                      <select value={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.value })} aria-label={t(name)}>
                        {["biologic", "small_molecule", "other", "unknown"].map((o) => <option key={o} value={o}>{tl(o)}</option>)}
                      </select>
                    ) : (
                      <input style={{ width: "100%" }} value={values[k]} placeholder={t("unknown")} aria-label={t(name)}
                        onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
                    )}
                    {isList && <div className="tiny muted">{t("comma-separated")}</div>}
                  </td>
                  <td><Badge tone={STATUS_TONE[f.status]}>{tl(f.status)}</Badge><div className="tiny muted" style={{ maxWidth: 220 }}>{f.explanation}</div></td>
                  <td>{f.evidence.length ? f.evidence.map((q: string, i: number) => <div key={i} className="quote">“{q}”</div>) : <span className="muted small">{t("none")}</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {proposal.follow_up_questions?.length > 0 && (
        <div className="alert info" style={{ display: "block" }}>
          <b>{t("Follow-up questions")}</b>
          <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>{proposal.follow_up_questions.map((q: string) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}
      <div className="alert warning"><span>!</span><span><b>{t("Regulatory caution:")}</b> {proposal.regulatory_caution}</span></div>
      {proposal._verification_notes?.length > 0 && <div className="tiny muted">{t("Evidence check:")} {proposal._verification_notes.join("; ")}</div>}
      <label className="f" style={{ marginTop: 8 }}>{t("Public search keywords (non-confidential; used for external research)")}
        <input value={values.public_keywords} onChange={(e) => setValues({ ...values, public_keywords: e.target.value })} />
      </label>
    </div>
  );
}

function initialValues(p: Json) {
  const v: Json = {};
  for (const [k] of FIELDS) {
    const val = p[k].value;
    v[k] = Array.isArray(val) ? val.join(", ") : val ?? (k === "use_type" || k === "molecule_category" ? "unknown" : "");
  }
  v.public_keywords = (p.public_search_terms || []).join(", ");
  v.stage_template = p.suggested_stage_template;
  return v;
}

function toProfile(v: Json) {
  const list = (s: string) => s.split(",").map((x: string) => x.trim()).filter(Boolean);
  const opt = (s: string) => (s && s.trim() && s.trim() !== "unknown" ? s.trim() : null);
  return {
    use_type: v.use_type, species: list(v.species), therapeutic_area: opt(v.therapeutic_area), indication: opt(v.indication), modality: opt(v.modality),
    molecule_category: v.molecule_category, target: opt(v.target), mechanism: opt(v.mechanism), route: opt(v.route),
    jurisdictions: list(v.jurisdictions).map((j: string) => j.toUpperCase()), public_keywords: list(v.public_keywords),
    stage_template: v.use_type === "human" ? "human" : "veterinary",
  };
}

function NewProgram({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Json>(null);
  const [values, setValues] = useState<Json>(null);
  const propose = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post("/api/classify", { description: desc, language: lang });
      setRes(r);
      setValues(initialValues(r.proposal));
    } catch (e: Json) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const create = async (confirm: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const profile = values ? toProfile(values) : {};
      const p = await api.post("/api/programs", { code, name, description: desc, ...(confirm ? {} : profile) });
      if (confirm && res) await api.post(`/api/programs/${p.id}/confirm-profile`, { proposal_id: res.proposal_id, profile });
      onCreated();
      nav(`/pipelines/${p.id}`);
    } catch (e: Json) {
      setErr(e.message);
      setBusy(false);
    }
  };
  return (
    <Modal title={t("New program")} onClose={onClose}>
      <div className="steps-mini">{t("1 Describe → 2 Review the AI proposal → 3 Confirm")}</div>
      <div className="form-grid">
        <label className="f">{t("Internal identifier")}<input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t("e.g. HX-401")} /></label>
        <label className="f">{t("Program name")}<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      </div>
      <label className="f" style={{ marginTop: 10 }}>
        {t("Short description (the classification agent proposes a structured profile from this)")}
        <textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder={t("We are developing an oral small-molecule kinase inhibitor for canine mast cell tumors and initially considering the US and EU.")} />
      </label>
      <div className="tiny muted">{t("The description is sent to the configured model provider only for this classification. It is never used in public searches.")}</div>
      <div className="row" style={{ margin: "10px 0" }}>
        <button className="primary" disabled={busy || desc.length < 10} onClick={propose}>{busy && !res ? t("Proposing…") : t("Propose profile")}</button>
        <button disabled={busy || !code || !name} onClick={() => create(false)}>{t("Create without AI profile")}</button>
      </div>
      {err && <ErrorBox error={err} />}
      {res && values && (
        <>
          <div className="row" style={{ marginBottom: 6 }}>
            <Prov kind="ai" /> <span className="small muted">{res.method === "rule_based_demo" ? t("Demo mode: rule-based classifier (no model call).") : t("Proposed by the Pipeline Classification Agent.")} {t("Review and correct before confirming.")}</span>
          </div>
          <ProposalReview proposal={res.proposal} values={values} setValues={setValues} />
          <RunTrace run={res.run} />
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy || !code || !name} onClick={() => create(true)}>{t("Create program and confirm reviewed profile")}</button>
          </div>
        </>
      )}
    </Modal>
  );
}

// ------------------------------------------------------------- detail

function MilestoneForm({ programId, milestones, initial, onDone }: { programId: number; milestones: Json[]; initial?: Json; onDone: () => void }) {
  const { t, tl } = useI18n();
  const [v, setV] = useState<Json>(initial || { name: "", stage: "", planned_start: "", planned_end: "", status: "planned", owner: "", is_decision_point: false, depends_on: [], notes: "" });
  const [err, setErr] = useState<string | null>(null);
  const ref = useApi("/api/reference");
  const prog = useApi(`/api/programs/${programId}`);
  const stages = prog.data?.stage_template === "human" ? ref.data?.human_stages : ref.data?.vet_stages;
  const save = async (setBaseline = false) => {
    setErr(null);
    const body: Json = { ...v, planned_start: v.planned_start || null, planned_end: v.planned_end || null, set_baseline: setBaseline };
    for (const k of ["id", "program_id", "overdue", "baseline_slip_days", "baseline_start", "baseline_end", "created_at", "updated_at", "origin", "actual_end"]) delete body[k];
    try {
      if (initial?.id) await api.patch(`/api/milestones/${initial.id}`, body);
      else await api.post(`/api/programs/${programId}/milestones`, body);
      onDone();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  return (
    <div className="card flat" style={{ background: "var(--sand-50)" }}>
      <div className="form-grid">
        <label className="f">{t("Milestone name")}<input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></label>
        <label className="f">{t("Stage ({x} template)", { x: t(prog.data?.stage_template === "human" ? "human" : "veterinary") })}
          <select value={v.stage || ""} onChange={(e) => setV({ ...v, stage: e.target.value })}><option value="">—</option>{(stages || []).map((s: string) => <option key={s} value={s}>{t(s)}</option>)}</select>
        </label>
        <label className="f">{t("Planned start")}<input type="date" value={v.planned_start || ""} onChange={(e) => setV({ ...v, planned_start: e.target.value })} /></label>
        <label className="f">{t("Planned end")}<input type="date" value={v.planned_end || ""} onChange={(e) => setV({ ...v, planned_end: e.target.value })} /></label>
        <label className="f">{t("Status")}<select value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>{["planned", "in_progress", "done", "at_risk", "cancelled"].map((s) => <option key={s} value={s}>{tl(s)}</option>)}</select></label>
        <label className="f">{t("Owner")}<input value={v.owner || ""} onChange={(e) => setV({ ...v, owner: e.target.value })} /></label>
        <label className="f">{t("Depends on")}
          <select multiple value={(v.depends_on || []).map(String)} onChange={(e) => setV({ ...v, depends_on: Array.from(e.target.selectedOptions).map((o) => Number(o.value)) })} style={{ minHeight: 64 }}>
            {milestones.filter((m) => m.id !== initial?.id).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
        <label className="row small"><input type="checkbox" checked={!!v.is_decision_point} onChange={(e) => setV({ ...v, is_decision_point: e.target.checked })} /> {t("Decision point")}</label>
      </div>
      <label className="f" style={{ marginTop: 8 }}>{t("Notes / risks")}<textarea value={v.notes || ""} onChange={(e) => setV({ ...v, notes: e.target.value })} /></label>
      {err && <ErrorBox error={err} />}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary" onClick={() => save(false)} disabled={!v.name}>{t("Save")}</button>
        <button onClick={() => save(true)} disabled={!v.name} title={t("Record these dates as the approved baseline (logged)")}>{t("Save and set as baseline")}</button>
        <button onClick={onDone}>{t("Cancel")}</button>
      </div>
    </div>
  );
}

function ResearchButtons({ program, onDone }: { program: Json; onDone: () => void }) {
  const { t, tl } = useI18n();
  const status = useStatus();
  const [job, setJob] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (kind: string) => {
    setErr(null);
    try {
      const j = await api.post(`/api/programs/${program.id}/research/${kind}`);
      setJob({ ...j, kind, status: "running" });
      const final = await waitForJob(j.job_id, (x) => setJob({ ...x, kind }));
      setJob({ ...final, kind });
      onDone();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const disabled = !program.profile_confirmed_at || (job && ["running", "queued"].includes(job.status));
  const kinds: Record<string, string> = { competitors: t("Competitor refresh"), regulatory: t("Regulatory research"), partners: t("Partner assessment") };
  return (
    <div>
      <div className="row">
        <button disabled={disabled} onClick={() => run("competitors")}>{t("Refresh competitor intelligence")}</button>
        <button disabled={disabled} onClick={() => run("regulatory")}>{t("Refresh regulatory research")}</button>
        <button disabled={disabled} onClick={() => run("partners")}>{t("Assess potential partners")}</button>
        {job && ["running", "queued"].includes(job.status) && <button className="danger" onClick={() => api.post(`/api/jobs/${job.job_id || job.id}/cancel`)}>{t("Cancel")}</button>}
      </div>
      {!program.profile_confirmed_at && <div className="tiny muted">{t("Confirm the profile first: research uses only confirmed, non-confidential profile fields.")}</div>}
      <div className="tiny muted">{status?.mode === "demo" ? t("Demo mode uses labeled fixtures.") : t("Live mode retrieves real public sources and calls the model.")}</div>
      {job && (
        <div className="small" style={{ marginTop: 6 }}>
          {kinds[job.kind] || job.kind}: <StatusPill status={job.status} /> {job.error && <span style={{ color: "var(--bad)" }}>{job.error}</span>}
          {job.result?.counts && <span className="muted"> · {Object.entries(job.result.counts).map(([k, v]) => `${tl(k)} ${v}`).join(" · ")}</span>}
        </div>
      )}
      {err && <ErrorBox error={err} />}
    </div>
  );
}

function ProfileEditor({ program, onSaved, onCancel }: { program: Json; onSaved: () => void; onCancel: () => void }) {
  const { t, tl } = useI18n();
  const ref = useApi("/api/reference");
  const [v, setV] = useState<Json>({ ...program, species: program.species.join(", "), jurisdictions: program.jurisdictions.join(", "), public_keywords: program.public_keywords.join(", ") });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    const list = (s: string) => s.split(",").map((x: string) => x.trim()).filter(Boolean);
    const body = {
      code: v.code, name: v.name, description: v.description, therapeutic_area: v.therapeutic_area || null, indication: v.indication || null, use_type: v.use_type,
      species: list(v.species), target: v.target || null, mechanism: v.mechanism || null, modality: v.modality || null, molecule_category: v.molecule_category,
      route: v.route || null, stage_template: v.stage_template, stage: v.stage || null, status: v.status, owner: v.owner || null, priority: v.priority,
      jurisdictions: list(v.jurisdictions).map((j: string) => j.toUpperCase()), risks: v.risks || null, notes: v.notes || null, public_keywords: list(v.public_keywords),
    };
    try {
      await api.patch(`/api/programs/${program.id}`, body);
      onSaved();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  const inp = (k: string, name: string) => <label className="f">{t(name)}<input value={v[k] || ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></label>;
  const stages = v.stage_template === "human" ? ref.data?.human_stages : ref.data?.vet_stages;
  return (
    <div>
      <div className="form-grid">
        {inp("code", "Internal identifier")}{inp("name", "Name")}
        <label className="f">{t("Use")}<select value={v.use_type} onChange={(e) => setV({ ...v, use_type: e.target.value })}>{["veterinary", "human", "unknown"].map((o) => <option key={o} value={o}>{tl(o)}</option>)}</select></label>
        {inp("species", "Species (comma-separated)")}{inp("therapeutic_area", "Therapeutic area")}{inp("indication", "Indication")}{inp("target", "Target")}{inp("mechanism", "Mechanism")}{inp("modality", "Modality")}
        <label className="f">{t("Molecule category")}<select value={v.molecule_category} onChange={(e) => setV({ ...v, molecule_category: e.target.value })}>{["biologic", "small_molecule", "other", "unknown"].map((o) => <option key={o} value={o}>{tl(o)}</option>)}</select></label>
        {inp("route", "Route")}
        <label className="f">{t("Stage template")}<select value={v.stage_template} onChange={(e) => setV({ ...v, stage_template: e.target.value })}><option value="veterinary">{t("Veterinary")}</option><option value="human">{t("Human")}</option></select></label>
        <label className="f">{t("Stage")}<select value={v.stage || ""} onChange={(e) => setV({ ...v, stage: e.target.value })}><option value="">—</option>{(stages || []).map((s: string) => <option key={s} value={s}>{t(s)}</option>)}</select></label>
        <label className="f">{t("Status")}<select value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>{["active", "on_hold", "discontinued", "completed"].map((s) => <option key={s} value={s}>{tl(s)}</option>)}</select></label>
        {inp("owner", "Owner")}
        <label className="f">{t("Priority")}<select value={v.priority} onChange={(e) => setV({ ...v, priority: e.target.value })}>{["high", "medium", "low"].map((o) => <option key={o} value={o}>{tl(o)}</option>)}</select></label>
        {inp("jurisdictions", "Jurisdictions (US, EU, CN, JP, KR…)")}{inp("public_keywords", "Public search keywords")}
      </div>
      <label className="f" style={{ marginTop: 8 }}>{t("Description")}<textarea value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></label>
      <div className="grid g2" style={{ marginTop: 8 }}>
        <label className="f">{t("Risks (internal)")}<textarea value={v.risks || ""} onChange={(e) => setV({ ...v, risks: e.target.value })} /></label>
        <label className="f">{t("Notes (internal, never sent to public search)")}<textarea value={v.notes || ""} onChange={(e) => setV({ ...v, notes: e.target.value })} /></label>
      </div>
      {err && <ErrorBox error={err} />}
      <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={save}>{t("Save profile")}</button><button onClick={onCancel}>{t("Cancel")}</button></div>
    </div>
  );
}

function Reclassify({ program, onDone }: { program: Json; onDone: () => void }) {
  const { t, lang } = useI18n();
  const [res, setRes] = useState<Json>(null);
  const [values, setValues] = useState<Json>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const propose = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post("/api/classify", { description: program.description, program_id: program.id, language: lang });
      setRes(r);
      setValues(initialValues(r.proposal));
    } catch (e: Json) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    try {
      await api.post(`/api/programs/${program.id}/confirm-profile`, { proposal_id: res.proposal_id, profile: toProfile(values) });
      onDone();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  return (
    <div>
      <button onClick={propose} disabled={busy || (program.description || "").length < 10}>{busy ? t("Proposing…") : t("Propose profile from description")}</button>
      {err && <ErrorBox error={err} />}
      {res && values && (
        <div style={{ marginTop: 10 }}>
          <ProposalReview proposal={res.proposal} values={values} setValues={setValues} />
          <RunTrace run={res.run} />
          <button className="primary" style={{ marginTop: 8 }} onClick={confirm}>{t("Confirm reviewed profile")}</button>
        </div>
      )}
    </div>
  );
}

export function ProgramDetail() {
  const { t, tl } = useI18n();
  const { id } = useParams();
  const { data: p, error, reload } = useApi(`/api/programs/${id}`);
  const tlData = useApi(`/api/timeline?program_id=${id}`);
  const [editing, setEditing] = useState(false);
  const [msForm, setMsForm] = useState<Json>(null);
  if (error) return <ErrorBox error={error} />;
  if (!p) return <Loading />;
  const tlById: Record<number, Json> = {};
  for (const m of tlData.data?.milestones || []) tlById[m.id] = m;
  const refresh = () => { reload(); tlData.reload(); };
  const ccy = tlData.data?.currency || "USD";
  return (
    <div>
      <div className="small"><Link to="/pipelines">← {t("Pipelines")}</Link></div>
      <PageHead title={`${p.code} · ${p.name}`} question={t("Profile, milestones and funding for this program")}
        next={[[`/budget?program=${p.id}`, t("Budgets")], [`/competitors?program=${p.id}`, t("Competitor events")], [`/regulatory?program=${p.id}`, t("Regulatory documents")], [`/markets?program=${p.id}`, t("Partners")]]}>
        <button onClick={() => setEditing(!editing)}>{editing ? t("Close editor") : t("Edit profile")}</button>
        <button onClick={async () => { await api.post(`/api/programs/${p.id}/archive?archived=${!p.archived}`); reload(); }}>{p.archived ? t("Unarchive") : t("Archive")}</button>
      </PageHead>
      <div className="row" style={{ marginTop: -8, marginBottom: 12 }}>
        <Prov kind={p.origin} /> <StatusPill status={p.status} /> <Badge>{t("{p} priority", { p: tl(p.priority) })}</Badge>
        {p.profile_confirmed_at ? <Badge tone="good">✓ {t("profile confirmed {d}", { d: p.profile_confirmed_at.slice(0, 10) })}</Badge> : <Badge tone="warn">! {t("profile not confirmed")}</Badge>}
        {p.archived && <Badge>{t("archived")}</Badge>}
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>{t("Profile")}</h2>
          {editing ? (
            <ProfileEditor program={p} onSaved={() => { setEditing(false); reload(); }} onCancel={() => setEditing(false)} />
          ) : (
            <>
              <p className="small">{p.description || <span className="muted">{t("No description")}</span>}</p>
              <dl className="kv">
                <dt>{t("Use / species")}</dt><dd>{tl(p.use_type)} · {p.species.join(", ") || t("unknown")}</dd>
                <dt>{t("Indication")}</dt><dd>{p.therapeutic_area || "—"} · {p.indication || t("unknown")}</dd>
                <dt>{t("Modality")}</dt><dd>{p.modality || t("unknown")} ({tl(p.molecule_category)})</dd>
                <dt>{t("Target / mechanism")}</dt><dd>{p.target || t("unknown")} · {p.mechanism || t("unknown")}</dd>
                <dt>{t("Route")}</dt><dd>{p.route || t("unknown")}</dd>
                <dt>{t("Stage")}</dt><dd>{p.stage ? t(p.stage) : "—"} <span className="muted small">({t(p.stage_template)})</span></dd>
                <dt>{t("Jurisdictions")}</dt><dd>{p.jurisdictions.join(", ") || "—"}</dd>
                <dt>{t("Owner")}</dt><dd>{p.owner || "—"}</dd>
                <dt>{t("Public keywords")}</dt><dd>{p.public_keywords.join(", ") || "—"}</dd>
                <dt>{t("Risks")}</dt><dd className="small">{p.risks || "—"}</dd>
              </dl>
              {p.profile_confirmed_at && <div className="tiny muted" style={{ marginTop: 6 }}>{t("Confirmed profiles drive research. Internal notes, risks, budgets and the program code are never used in public queries.")}</div>}
            </>
          )}
        </div>
        <div className="card">
          <h2>{t("AI classification")}</h2>
          <Reclassify program={p} onDone={reload} />
          {p.proposals?.length > 0 && <div className="tiny muted" style={{ marginTop: 8 }}>{t("Past proposals:")} {p.proposals.map((x: Json) => `#${x.id} ${tl(x.status)}`).join(", ")}</div>}
          <h2 style={{ marginTop: 16 }}>{t("External research")}</h2>
          <ResearchButtons program={p} onDone={refresh} />
        </div>
      </div>
      <div className="card">
        <div className="card-head">
          <h2>{t("Milestones, dependencies and funding")}</h2>
          <button className="primary" onClick={() => setMsForm({})}>+ {t("Add milestone")}</button>
        </div>
        {msForm && <MilestoneForm programId={p.id} milestones={p.milestones} initial={msForm.id ? msForm : undefined} onDone={() => { setMsForm(null); refresh(); }} />}
        {p.milestones.length === 0 ? <Empty title={t("No milestones yet")}>{t("Add the next scientific milestones to plan budgets and test funding.")}</Empty> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>{t("Milestone")}</th><th>{t("Stage")}</th><th>{t("Planned")}</th><th>{t("Baseline end")}</th><th>{t("Status")}</th><th>{t("Depends on")}</th><th className="n">{t("Approved")}</th><th className="n">{t("Paid")}</th><th className="n">{t("Remaining")}</th><th>{t("Funding")}</th><th /></tr></thead>
              <tbody>
                {p.milestones.map((m: Json) => {
                  const x = tlById[m.id];
                  return (
                    <tr key={m.id}>
                      <td>{m.is_decision_point && "◆ "}{m.name}</td>
                      <td className="small">{m.stage ? t(m.stage) : "—"}</td>
                      <td className="small">{dateOnly(m.planned_start)} → {dateOnly(m.planned_end)}</td>
                      <td className="small">{dateOnly(m.baseline_end)}{m.baseline_slip_days ? <div className="tiny" style={{ color: "var(--warn)" }}>{t("slip {n} days", { n: m.baseline_slip_days })}</div> : null}</td>
                      <td><StatusPill status={m.status} /> {m.overdue && <StatusPill status="overdue" />}</td>
                      <td className="small">{m.depends_on.map((d: number) => p.milestones.find((y: Json) => y.id === d)?.name).join(", ") || "—"}</td>
                      <td className="n">{x?.budget ? money(x.budget.approved_minor, ccy, { compact: true }) : "—"}</td>
                      <td className="n">{x?.budget ? money(x.budget.actual_minor, ccy, { compact: true }) : "—"}</td>
                      <td className="n">{x?.budget ? money(x.budget.remaining_minor, ccy, { compact: true }) : <span className="muted">{t("no budget")}</span>}</td>
                      <td>{x?.funding ? (x.funding.funded === true ? <Badge tone="good">✓ {t("funded")}</Badge> : x.funding.funded === false ? <Badge tone="bad">✕ {t("gap {g}", { g: money(x.funding.gap_minor, ccy, { compact: true }) })}</Badge> : <Badge>• {t("unknown")}</Badge>) : "—"}</td>
                      <td><button className="link small" onClick={() => setMsForm(m)}>{t("Edit")}</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {tlData.data && <PhaseMap timeline={tlData.data.milestones} currency={ccy} programId={Number(id)} />}
    </div>
  );
}
