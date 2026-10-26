import { useEffect, useState } from "react";
import { api, type Json } from "../api";
import { useStatus } from "../App";
import { Badge, ErrorBox, Loading, PageHead, RunTrace, StatusPill, Tabs, useApi } from "../components/ui";
import { dateTime, num } from "../format";
import { useI18n } from "../i18n";

export default function Settings() {
  const { t } = useI18n();
  const [tab, setTab] = useState("company");
  return (
    <div>
      <PageHead title={t("Settings and Activity")} question={t("Our mission, how the app is set up, what the AI has done, and who changed what.")} />
      <Tabs value={tab} onChange={setTab} tabs={[
        ["company", t("Mission and values"), t("Shown at the top of the Overview so nobody forgets why we started.")],
        ["status", t("Status and limits"), t("Mode, model provider, safety limits, confidential terms.")],
        ["runs", t("Agent runs and usage"), t("Every AI run: tokens, cost, cache hits, trace.")],
        ["jobs", t("Jobs"), t("Background research jobs and their results.")],
        ["activity", t("Activity log"), t("Audit trail of every change.")],
      ]} />
      {tab === "company" && <CompanyTab />}
      {tab === "status" && <StatusTab />}
      {tab === "runs" && <Runs />}
      {tab === "jobs" && <Jobs />}
      {tab === "activity" && <Activity />}
    </div>
  );
}

function CompanyTab() {
  const { t } = useI18n();
  const { data, reload } = useApi("/api/settings/company");
  const [mission, setMission] = useState("");
  const [values, setValues] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (data) {
      setMission(data.mission || "");
      setValues((data.values || []).join("\n"));
    }
  }, [data]);
  const save = async () => {
    setErr(null);
    try {
      await api.put("/api/settings/company", { mission, values: values.split("\n").map((v) => v.trim()).filter(Boolean) });
      setMsg(t("Saved"));
      reload();
    } catch (e: Json) {
      setErr(e.message);
    }
  };
  if (!data) return <Loading />;
  return (
    <div className="card" style={{ maxWidth: 760 }}>
      <h2>{t("Mission and values")}</h2>
      <label className="f">{t("Mission statement (leave blank to show the draft)")}
        <textarea value={mission} onChange={(e) => setMission(e.target.value)} placeholder={t("Bring better cancer medicines to dogs, cats and the families who love them.")} />
      </label>
      <label className="f" style={{ marginTop: 10 }}>{t("Core values (one per line)")}
        <textarea value={values} onChange={(e) => setValues(e.target.value)} />
      </label>
      {err && <ErrorBox error={err} />}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary" onClick={save}>{t("Save")}</button>
        {msg && <span className="small">✓ {msg}</span>}
      </div>
      <div className="tiny muted" style={{ marginTop: 8 }}>{t("Values in the default list (such as “All life matters”) are translated automatically; custom text is shown as written.")}</div>
    </div>
  );
}

function StatusTab() {
  const { t, tl } = useI18n();
  const s = useStatus();
  const terms = useApi("/api/settings/confidential-terms");
  const [x, setX] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (!s) return <Loading />;
  return (
    <div className="grid g2">
      <div className="card">
        <h2>{t("Mode and model provider")}</h2>
        <dl className="kv">
          <dt>{t("Mode")}</dt><dd><Badge tone={s.mode === "live" ? "good" : "warn"}>{tl(s.mode)}</Badge></dd>
          <dt>{t("Provider")}</dt><dd>{s.provider} {s.gateway && <span className="small muted">{t("via {g}", { g: s.gateway })}</span>}</dd>
          <dt>{t("Model")}</dt><dd>{s.model || "—"}</dd>
          <dt>{t("Live model calls")}</dt><dd>{s.ready ? <Badge tone="good">✓ {t("ready")}</Badge> : s.mode === "demo" ? <Badge>{t("off (demo mode)")}</Badge> : <Badge tone="bad">✕ {t("not ready")}</Badge>}</dd>
          <dt>{t("Keys present")}</dt><dd>{t("Portkey {p} · OpenAI {o}", { p: s.portkey_key_present ? t("yes") : t("no"), o: s.openai_key_present ? t("yes") : t("no") })} {Object.keys(s.key_origin || {}).length > 0 && <span className="small muted">({t("loaded from {o}", { o: Object.values(s.key_origin).join(", ") })})</span>}</dd>
          <dt>{t("Database")}</dt><dd>{s.database}</dd>
          <dt>{t("Timezone")}</dt><dd>{s.timezone}</dd>
        </dl>
        {s.errors?.map((e: string) => <div key={e} className="alert error">✕ {e}</div>)}
        <div className="tiny muted" style={{ marginTop: 8 }}>{t("Keys stay on the server and are never shown or logged. The course Portkey key is used only with gpt-6-luna; the app never switches providers or models silently. Change mode and provider in .env and restart.")}</div>
      </div>
      <div className="card">
        <h2>{t("Limits")}</h2>
        <table className="t"><tbody>{Object.entries(s.limits).map(([k, v]) => <tr key={k}><td>{tl(k)}</td><td className="n">{num(v as number, 1)}</td></tr>)}</tbody></table>
        <div className="section-label">{t("Scheduler")}</div>
        <p className="small">{t("Automatic refresh runs only while this app (or the scheduled daily-job command) is running on a computer that is awake.")} {s.scheduler.enabled_in_app ? t("In-app scheduler: on (after {h}:00 local).", { h: s.scheduler.briefing_hour_local }) : t("In-app scheduler: off.")} {t("See README → “Daily refresh”.")}</p>
      </div>
      <div className="card">
        <h2>{t("Confidential terms")}</h2>
        <p className="small muted">{t("Comma-separated words that must never appear in public search queries (program codes are always blocked). For example: company name, internal project nicknames, partner names under NDA.")}</p>
        <textarea value={x ?? terms.data?.terms ?? ""} onChange={(e) => setX(e.target.value)} aria-label={t("Confidential terms")} />
        <button style={{ marginTop: 6 }} onClick={async () => { await api.put(`/api/settings/confidential-terms?terms=${encodeURIComponent(x ?? "")}`); setMsg(t("Saved")); terms.reload(); }}>{t("Save")}</button>
        {msg && <span className="small"> ✓ {msg}</span>}
      </div>
      <div className="card">
        <h2>{t("Access boundary")}</h2>
        <p className="small">{t("Local prototype: the API listens on 127.0.0.1 only and has no user accounts. Anyone with access to this computer account can use it. See docs/SECURITY.md before sharing.")}</p>
        {s.mode === "demo" && <button className="danger" onClick={async () => { if (window.confirm(t("Reset the demo database to the synthetic starting state?"))) { await api.post("/api/demo/reset"); window.location.reload(); } }}>{t("Reset demo data")}</button>}
      </div>
    </div>
  );
}

function Runs() {
  const { t, tl } = useI18n();
  const m = useApi("/api/metrics?days=30");
  const r = useApi("/api/agent-runs?limit=60");
  return (
    <div>
      <div className="card">
        <h2>{t("Usage by agent (last 30 days)")}</h2>
        {!m.data ? <Loading /> : (
          <>
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>{t("Agent")}</th><th>{t("Mode")}</th><th className="n">{t("Runs")}</th><th className="n">{t("Failed/refused")}</th><th className="n">{t("Input tokens")}</th><th className="n">{t("Cached input")}</th><th className="n">{t("Output tokens")}</th><th className="n">{t("Tool calls")}</th><th className="n">{t("Avg latency")}</th><th className="n">{t("App cache hits/misses")}</th><th className="n">{t("Gateway cache hits/misses")}</th><th className="n">{t("Quarantined")}</th><th className="n">{t("Est. cost (USD)")}</th></tr></thead>
                <tbody>{m.data.by_agent.map((a: Json) => (
                  <tr key={a.agent + a.mode}><td>{tl(a.agent)}</td><td>{tl(a.mode)}</td><td className="n">{a.runs}</td><td className="n">{a.not_succeeded}</td><td className="n">{num(a.input_tokens)}</td><td className="n">{num(a.cached_input_tokens)}</td><td className="n">{num(a.output_tokens)}</td><td className="n">{num(a.tool_calls)}</td><td className="n">{num(a.avg_ms)} ms</td><td className="n">{num(a.cache_hits)}/{num(a.cache_misses)}</td><td className="n">{a.gateway_hits == null && a.gateway_misses == null ? "—" : `${num(a.gateway_hits)}/${num(a.gateway_misses)}`}</td><td className="n">{num(a.quarantined)}</td><td className="n">{a.mode === "live" ? (a.cost_usd != null ? `$${Number(a.cost_usd).toFixed(4)}` : t("unknown")) : "—"}{a.runs_cost_unknown ? <div className="tiny muted">{t("{n} unknown", { n: a.runs_cost_unknown })}</div> : null}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <ul className="small muted">
              <li>{t("Token counts are provider-reported. Demo-mode runs have no tokens and are never simulated.")}</li>
              <li>{t("Costs are estimates from the dated pricing table; unknown when a price is missing.")}</li>
              <li>{t("App cache hits = public retrieval reused from the shared cache. Gateway cache hits = Portkey replayed an earlier identical model response (costed at $0; billing unverified). Cached input tokens = provider-side prompt caching. They are different things.")}</li>
            </ul>
            <div className="small">{t("Pricing table:")} {Object.entries(m.data.pricing.models || {}).map(([k, v]: Json) => t("{k}: ${i}/M input, ${c}/M cached, ${o}/M output (as of {d}; third-party sources, not verified against course billing)", { k, i: v.input_usd_per_mtok, c: v.cached_input_usd_per_mtok, o: v.output_usd_per_mtok, d: v.as_of })).join(" ")}</div>
            <div className="small muted">{t("Public research cache: {n} URLs, {h} reuse hits, latest retrieval {d}.", { n: m.data.public_cache.n, h: num(m.data.public_cache.hits), d: dateTime(m.data.public_cache.latest) })}</div>
          </>
        )}
      </div>
      <div className="card">
        <h2>{t("Recent runs")}</h2>
        {!r.data ? <Loading /> : r.data.map((x: Json) => (
          <div key={x.id} style={{ borderBottom: "1px solid var(--line)", padding: "6px 0" }}>
            <div className="row small"><b>#{x.id} {tl(x.agent)}</b> <StatusPill status={x.status} /> <span className="muted">{dateTime(x.started_at)} · {x.provider || t("none")} {x.model || ""}</span></div>
            <RunTrace run={x} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Jobs() {
  const { t, tl } = useI18n();
  const { data, reload } = useApi("/api/jobs");
  if (!data) return <Loading />;
  return (
    <div className="card">
      <button onClick={reload}>{t("Refresh")}</button>
      <table className="t" style={{ marginTop: 8 }}>
        <thead><tr><th>#</th><th>{t("Kind")}</th><th>{t("Params")}</th><th>{t("Status")}</th><th>{t("Created")}</th><th>{t("Finished")}</th><th>{t("Error / result")}</th><th /></tr></thead>
        <tbody>{data.map((j: Json) => (
          <tr key={j.id}><td>{j.id}</td><td>{tl(j.kind)}</td><td className="small">{JSON.stringify(j.params)}</td><td><StatusPill status={j.status} /></td><td className="small">{dateTime(j.created_at)}</td><td className="small">{dateTime(j.finished_at)}</td>
            <td className="small" style={{ maxWidth: 360 }}>{j.error ? <span style={{ color: "var(--bad)" }}>{j.error}</span> : j.result?.counts ? Object.entries(j.result.counts).map(([k, v]) => `${tl(k)} ${v}`).join(" · ") : ""}</td>
            <td>{["queued", "running"].includes(j.status) && <button className="danger small" onClick={async () => { await api.post(`/api/jobs/${j.id}/cancel`); reload(); }}>{t("Cancel")}</button>}</td></tr>))}</tbody>
      </table>
    </div>
  );
}

function Activity() {
  const { t, tl } = useI18n();
  const [type, setType] = useState("");
  const { data, error } = useApi(`/api/activity?limit=300${type ? `&entity_type=${type}` : ""}`);
  return (
    <div className="card">
      <label className="f" style={{ maxWidth: 240 }}>{t("Filter")}<select value={type} onChange={(e) => setType(e.target.value)}><option value="">{t("All")}</option>{["program", "milestone", "budget_line", "import_batch", "transaction", "commitment", "scenario", "classification", "intel_events", "regulatory", "assistant", "settings"].map((x) => <option key={x} value={x}>{tl(x)}</option>)}</select></label>
      {error && <ErrorBox error={error} />}
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table className="t">
          <thead><tr><th>{t("Time")}</th><th>{t("Actor")}</th><th>{t("Action")}</th><th>{t("Entity")}</th><th>{t("Detail")}</th></tr></thead>
          <tbody>{(data || []).map((a: Json) => <tr key={a.id}><td className="small">{dateTime(a.ts)}</td><td className="small">{a.actor}</td><td>{tl(a.action)}</td><td className="small">{tl(a.entity_type)} {a.entity_id}</td><td className="tiny">{JSON.stringify(a.detail).slice(0, 200)}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
