import { useState } from "react";
import { api, type Json } from "../api";
import { useStatus } from "../App";
import { Cat } from "../components/pets";
import { Badge, ErrorBox, Loading, PageHead, Prov, RunTrace, useApi } from "../components/ui";
import { useI18n } from "../i18n";

const EXAMPLES = [
  "Can we afford the next milestone?",
  "Which pipeline is most over budget?",
  "What happens to runway if the pilot study starts three months later?",
  "What changed among our competitors this week?",
  "Which regulatory updates might affect our canine program?",
  "Which potential partners have the strongest documented fit?",
];

export default function Assistant() {
  const { t, lang } = useI18n();
  const status = useStatus();
  const progs = useApi("/api/programs");
  const [program, setProgram] = useState("");
  const [q, setQ] = useState("");
  const [log, setLog] = useState<Json[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post("/api/assistant/ask", { question, program_id: program ? Number(program) : null, language: lang });
      setLog([{ question, r }, ...log]);
      setQ("");
    } catch (e: Json) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <PageHead title={t("AI Assistant")} question={t("Ask anything about our programs, money, competitors, regulation or partners — in plain words.")}>
        <label className="f">{t("Context program")}<select value={program} onChange={(e) => setProgram(e.target.value)}><option value="">{t("All programs")}</option>{(progs.data || []).map((p: Json) => <option key={p.id} value={p.id}>{p.code}</option>)}</select></label>
      </PageHead>
      <div className="tiny muted" style={{ marginTop: -10, marginBottom: 10 }}>{t("The Planning Assistant answers from your records through read-only tools. Figures come from deterministic calculations; it cannot change budgets, milestones, or transactions.")}</div>
      {status?.mode === "demo" && <div className="alert info">i {t("Demo mode: answers come from deterministic templates over the same tools (no model call).")}</div>}
      <div className="card">
        <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="row">
          <span aria-hidden><Cat size={34} /></span>
          <label className="sr-only" htmlFor="q">{t("Question")}</label>
          <input id="q" style={{ flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Ask about funding, budgets, runway, competitors, regulation, partners…")} />
          <button className="primary" disabled={busy || !q.trim()}>{t("Ask")}</button>
        </form>
        <div className="small muted" style={{ margin: "8px 0 4px" }}>{t("Try one of these:")}</div>
        <div className="row small">{EXAMPLES.map((e) => <button key={e} className="small" onClick={() => ask(t(e))} disabled={busy}>{t(e)}</button>)}</div>
      </div>
      {busy && <Loading text={t("The assistant is calling tools…")} />}
      {err && <ErrorBox error={err} />}
      {log.map(({ question, r }, i) => (
        <div key={i}>
          <div className="chat-msg chat-q"><b>{t("You:")}</b> {question}</div>
          <div className="chat-msg chat-a">
            <div className="row" style={{ marginBottom: 6 }}><Prov kind="ai" /> {r.method === "template_demo" && <Badge>{t("template answer (demo)")}</Badge>}</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{r.answer}</div>
            {r.key_figures?.length > 0 && (
              <>
                <div className="section-label">{t("Key figures (from deterministic tools)")}</div>
                <table className="t"><tbody>{r.key_figures.map((f: Json, k: number) => <tr key={k}><td>{f.label}</td><td className="n"><b>{f.value}</b></td><td className="tiny muted">{f.tool}</td></tr>)}</tbody></table>
              </>
            )}
            {r.grounding?.unverified_figures?.length > 0 && <div className="alert warning">! {t("Figures not found in tool output (treat with caution): {f}", { f: r.grounding.unverified_figures.join(", ") })}</div>}
            {r.grounding?.removed_sources?.length > 0 && <div className="alert warning">! {t("Removed {n} source link(s) not returned by tools.", { n: r.grounding.removed_sources.length })}</div>}
            {r.sources?.length > 0 && <><div className="section-label">{t("Sources")}</div>{r.sources.map((s: Json, k: number) => <div key={k} className="small"><a href={s.url} target="_blank" rel="noopener noreferrer nofollow">{s.title || s.url} ↗</a>{s.retrieved_at && <span className="tiny muted"> · {t("retrieved")} {s.retrieved_at.slice(0, 10)}</span>}</div>)}</>}
            {r.assumptions?.length > 0 && <><div className="section-label"><Prov kind="assumption" /> {t("Assumptions")}</div><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.assumptions.map((a: string, k: number) => <li key={k}>{a}</li>)}</ul></>}
            {r.gaps?.length > 0 && <><div className="section-label">{t("Gaps and data warnings")}</div><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.gaps.map((a: string, k: number) => <li key={k}>{a}</li>)}</ul></>}
            {r.suggested_actions?.length > 0 && <><div className="section-label">{t("Suggested for human review")}</div><ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{r.suggested_actions.map((a: string, k: number) => <li key={k}>{a}</li>)}</ul></>}
            <div style={{ marginTop: 8 }}><RunTrace run={r.run} /></div>
          </div>
        </div>
      ))}
    </div>
  );
}
