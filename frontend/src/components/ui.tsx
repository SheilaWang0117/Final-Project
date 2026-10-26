import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Json } from "../api";
import { useI18n } from "../i18n";
import { Paw, SleepingCat } from "./pets";

// ----------------------------------------------------------------- provenance

const PROV: Record<string, { cls: string; text: string; title: string }> = {
  internal: { cls: "b-internal", text: "Internal", title: "Entered by your team" },
  user: { cls: "b-internal", text: "Internal", title: "Entered by your team" },
  import: { cls: "b-internal", text: "Imported", title: "Imported from your spreadsheet" },
  external: { cls: "b-external", text: "External source", title: "Retrieved from a public source (see link and date)" },
  ai: { cls: "b-ai", text: "AI interpretation", title: "Written by an AI agent; review before relying on it" },
  agent: { cls: "b-ai", text: "AI research", title: "Produced by an AI research workflow from public sources" },
  assumption: { cls: "b-assumption", text: "Planning assumption", title: "An estimate or assumption, not a fact" },
  hypothesis: { cls: "b-assumption", text: "Hypothesis", title: "Explicitly speculative" },
  synthetic: { cls: "b-synthetic", text: "Synthetic demo", title: "Fictional demonstration data" },
  fixture: { cls: "b-fixture", text: "Demo fixture", title: "Synthetic research fixture, not real" },
};

export function Prov({ kind }: { kind: string | null | undefined }) {
  const { t } = useI18n();
  const p = PROV[kind || ""] || { cls: "b-neutral", text: kind || "unknown", title: "" };
  return (
    <span className={`badge ${p.cls}`} title={t(p.title)}>
      {t(p.text)}
    </span>
  );
}

export function Badge({ tone = "neutral", children, title }: { tone?: "good" | "warn" | "bad" | "neutral"; children: ReactNode; title?: string }) {
  return (
    <span className={`badge b-${tone}`} title={title}>
      {children}
    </span>
  );
}

const TONE: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  done: "good", succeeded: "good", funded: "good", active: "good", ok: "good", fresh: "good", approved: "good", final: "good", reviewed: "good",
  tracked: "good", committed: "good", confirmed: "good",
  in_progress: "neutral", planned: "neutral", open: "neutral", draft: "warn", partial: "warn", at_risk: "warn", proposed: "warn", suggested: "warn",
  needs_review: "warn", running: "neutral", queued: "neutral", validated: "neutral", hypothetical: "warn",
  failed: "bad", missing_balance: "bad", provider_error: "bad", timeout: "bad", interrupted: "bad", cancelled: "neutral", reversed: "bad",
  overdue: "bad", refused: "bad", limit_exceeded: "bad", invalid_output: "bad", content_filtered: "bad", blocked_secret: "bad",
};

// Status pill always carries text (never color alone).
export function StatusPill({ status }: { status: string }) {
  const { tl } = useI18n();
  const tone = TONE[status] || "neutral";
  const icon = { good: "✓", warn: "!", bad: "✕", neutral: "•" }[tone];
  return <Badge tone={tone}>{icon} {tl(status)}</Badge>;
}

// --------------------------------------------------------------- data states

export function Loading({ text }: { text?: string }) {
  const { t } = useI18n();
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="paw-walk" aria-hidden>
        <Paw size={14} color="#00918f" /> <Paw size={14} color="#00918f" /> <Paw size={14} color="#00918f" />
      </span>
      {text || t("Loading…")}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="alert error" role="alert">
      <span>✕</span>
      <div style={{ flex: 1 }}>{error}</div>
      {onRetry && <button onClick={onRetry}>{t("Retry")}</button>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <SleepingCat size={84} />
      <div style={{ fontWeight: 600, color: "var(--ink-2)", margin: "4px 0" }}>{title}</div>
      <div className="small">{children}</div>
    </div>
  );
}

export function Issues({ items, max = 8 }: { items: Json[] | undefined; max?: number }) {
  const { t, issue, lang } = useI18n();
  if (!items || !items.length) return null;
  return (
    <div>
      {items.slice(0, max).map((i: Json, k: number) => (
        <div key={k} className={`alert ${i.level === "error" ? "error" : i.level === "warning" ? "warning" : "info"}`}>
          <span aria-hidden>{i.level === "error" ? "✕" : i.level === "warning" ? "!" : "i"}</span>
          <span>
            <span className="sr-only">{i.level}: </span>
            {issue(i)}
            {lang === "zh" && issue(i) !== i.message && <span className="tiny muted" style={{ display: "block" }}>{i.message}</span>}
          </span>
        </div>
      ))}
      {items.length > max && <div className="tiny muted">{t("+{n} more", { n: items.length - max })}</div>}
    </div>
  );
}

export function Stat({ k, v, d, title, to }: { k: string; v: ReactNode; d?: ReactNode; title?: string; to?: string }) {
  const body = (
    <>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
    </>
  );
  return to ? <Link to={to} className="stat stat-link" title={title}>{body}</Link> : <div className="stat" title={title}>{body}</div>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const { t } = useI18n();
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button onClick={onClose} aria-label={t("Close dialog")}>{t("Close")}</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Source({ url, name, published, retrieved }: { url: string; name?: string; published?: string | null; retrieved?: string | null }) {
  const { t } = useI18n();
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    host = url;
  }
  return (
    <span className="small">
      <a href={url} target="_blank" rel="noopener noreferrer nofollow">
        {name || host} ↗
      </a>
      <span className="muted">
        {" "}· {t("published")} {published ? published.slice(0, 10) : t("date unknown")} · {t("retrieved")} {retrieved ? retrieved.slice(0, 10) : "—"}
      </span>
    </span>
  );
}

// Page header used on every page: what this page answers, and where to go next.
export function PageHead({ title, question, children, next }: { title: string; question: string; children?: ReactNode; next?: [string, string][] }) {
  const { t } = useI18n();
  return (
    <div className="topbar">
      <div>
        <h1>{title}</h1>
        <div className="page-question"><Paw size={13} color="#00918f" /> {question}</div>
        {next && next.length > 0 && (
          <div className="next-steps small">
            {t("Related:")}{" "}
            {next.map(([to, name], i) => (
              <span key={to}>
                {i > 0 && " · "}
                <Link to={to}>{name}</Link>
              </span>
            ))}
          </div>
        )}
      </div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- data hook

export function useApi<T = Json>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const load = useCallback(() => {
    if (!path) return;
    setLoading(true);
    setError(null);
    api
      .get(path)
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    load();
  }, [load]);
  return { data, error, loading, reload: load, setData };
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string, string?][]; value: string; onChange: (v: string) => void }) {
  const hint = tabs.find(([k]) => k === value)?.[2];
  return (
    <div>
      <div className="tabs" role="tablist">
        {tabs.map(([k, label, h]) => (
          <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)} title={h}>
            {label}
          </button>
        ))}
      </div>
      {hint && <div className="tab-hint">{hint}</div>}
    </div>
  );
}

export function RunTrace({ run }: { run: Json }) {
  const { t, tl } = useI18n();
  if (!run) return null;
  return (
    <details>
      <summary>
        {t("Execution trace")} · {tl(run.mode)} · {tl(run.status)} · {run.duration_ms ?? "?"} ms
        {run.input_tokens != null && ` · ${t("{i} in / {o} out tokens", { i: run.input_tokens, o: run.output_tokens })}`}
        {run.gateway_cache_hits ? ` · ${t("gateway cache hit {h}/{n} (replayed response)", { h: run.gateway_cache_hits, n: run.gateway_cache_hits + (run.gateway_cache_misses || 0) })}` : ""}
        {run.quarantined_items ? ` · ${t("{n} item(s) quarantined", { n: run.quarantined_items })}` : ""}
        {run.cost_usd != null ? ` · ${t("est.")} $${Number(run.cost_usd).toFixed(4)}` : run.mode === "live" ? ` · ${t("cost unknown")}` : ""}
      </summary>
      <div className="trace">
        {(run.trace || [])
          .map((s: Json) => `${s.ok ? "✓" : "✕"} ${s.step}${s.ms ? ` (${s.ms} ms)` : ""}${s.error ? ` — ${s.error}` : ""}${s.detail && Object.keys(s.detail).length ? `  ${JSON.stringify(s.detail).slice(0, 220)}` : ""}`)
          .join("\n")}
        {run.sources?.length ? `\n\n${t("Sources retrieved")} (${run.sources.length}):\n` + run.sources.slice(0, 12).map((s: Json) => `- ${s.title?.slice(0, 90)} ${s.from_cache ? "[cache]" : ""}`).join("\n") : ""}
        {run.error ? `\n\n${t("Error")}: ${run.error}` : ""}
      </div>
    </details>
  );
}
