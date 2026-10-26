import { useState } from "react";
import { Link } from "react-router-dom";
import { api, waitForJob, type Json } from "../api";
import { Cat, Dog } from "../components/pets";
import { Badge, Empty, ErrorBox, Loading, Modal, PageHead, Prov, Source, StatusPill, useApi } from "../components/ui";
import { dateTime } from "../format";
import { useI18n } from "../i18n";

const SECTIONS: [string, string][] = [["pipeline", "Pipeline-specific updates"], ["animal_health", "Veterinary oncology and animal health"], ["regulatory", "Regulatory updates"], ["lead_candidate", "Biotech industry"]];
const RULE_ZH = "得分 = 0.45 × 重要性（AI，0–100）+ 0.35 × 与管线相关性（AI，0–100）+ 0.10 × 时效性（今天 100，3 天后降为 0）+ 0.10 × 来源权威性（官方监管机构 100，登记/申报 85，文献索引 80，行业媒体 60）。头条为得分最高的报道。AI 评分属于判断；公式固定并公开。";

function Story({ s }: { s: Json }) {
  const { t, tl } = useI18n();
  return (
    <div className="event" style={s.lead ? { borderColor: "var(--teal-500)", borderWidth: 2 } : {}}>
      <div className="row">
        {s.lead && <Badge tone="good">★ {t("Lead story")}</Badge>}
        <Badge>{tl(s.section)}</Badge>
        {s.fixture && <Prov kind="fixture" />}
        <span className="tiny muted">
          {t("score {s} (significance {a}, relevance {b}, recency {c}, authority {d})", { s: s.score.total, a: s.score.significance, b: s.score.pipeline_relevance, c: s.score.recency, d: s.score.authority })}
        </span>
      </div>
      <h3 style={{ margin: "6px 0 2px" }}>{s.title}</h3>
      <Source url={s.url} name={s.source} published={s.published_at} retrieved={s.retrieved_at} />
      <dl className="layer">
        <dt><Prov kind={s.fixture ? "fixture" : "external"} /> {t("Summary")}</dt><dd>{s.summary}</dd>
        <dt><Prov kind="ai" /> {t("Why it matters")}</dt><dd>{s.why_it_matters}</dd>
      </dl>
    </div>
  );
}

export function BriefingBody({ data }: { data: Json }) {
  const { t, lang } = useI18n();
  const b = data.briefing;
  if (!b) return <Empty title={t("No briefing yet")}>{t("Generate one with “Refresh now”. Daily refresh runs from the scheduled job or while the app is running.")}</Empty>;
  const stories: Json[] = b.items.stories || [];
  const lead = stories.find((s) => s.lead);
  return (
    <div>
      <div className="row small" style={{ marginBottom: 8 }}>
        <StatusPill status={b.status} />
        {data.stale && <Badge tone="warn">! {t("stale")}</Badge>}
        <span className="muted">{t("Generated {g} for {d} ({z})", { g: dateTime(b.generated_at), d: b.briefing_date, z: b.timezone })}</span>
        {b.origin === "fixture" && <Prov kind="fixture" />}
      </div>
      {data.stale_reason && <div className="alert warning">! {data.stale && lang === "zh" ? t("显示的是最近一期简报（{d}），今天的简报尚未生成或获取失败。", { d: b.briefing_date }) : data.stale_reason}</div>}
      {b.status === "partial" && <div className="alert warning">! {t("Some sources failed: {s}", { s: Object.entries(b.coverage).filter(([, v]: Json) => !v.ok).map(([k]) => k).join(", ") })}</div>}
      {lang === "zh" && stories.length > 0 && <div className="tiny muted" style={{ marginBottom: 6 }}>{t("Research text is shown in its original language.")}</div>}
      {lead && <Story s={lead} />}
      {SECTIONS.map(([key, title]) => {
        const items = stories.filter((s) => s.section === key && !s.lead);
        if (!items.length) return null;
        return (
          <div key={key}>
            <div className="section-label">{t(title)}</div>
            {items.map((s, i) => <Story key={i} s={s} />)}
          </div>
        );
      })}
      <div className="section-label">{t("Internal milestones and financial risks")}</div>
      {(b.items.internal || []).length === 0 ? <div className="small muted">{t("Nothing due in the next 30 days.")}</div> : (
        b.items.internal.map((i: Json, k: number) => <div key={k} className={`alert ${i.level === "warning" ? "warning" : "info"}`}><span>{i.level === "warning" ? "!" : "i"}</span><span><Prov kind="internal" /> {i.text}</span></div>)
      )}
      <div className="tiny muted" style={{ marginTop: 8 }}>{t("Ranking rule:")} {lang === "zh" ? RULE_ZH : data.ranking_rule}</div>
    </div>
  );
}

export function BriefingPopup() {
  const { t } = useI18n();
  const { data } = useApi("/api/briefing");
  const [closed, setClosed] = useState(false);
  if (!data || !data.show_popup || closed) return null;
  const dismiss = async () => {
    setClosed(true);
    await api.post("/api/briefing/dismiss");
  };
  return (
    <Modal title={t("Good morning! Daily briefing · {d}", { d: data.today })} onClose={dismiss}>
      <div className="popup-pets" aria-hidden><Cat size={34} /><Dog size={34} /></div>
      <BriefingBody data={data} />
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" onClick={dismiss}>{t("Dismiss for today")}</button>
        <Link to="/briefing" onClick={dismiss}>{t("Open briefing page")}</Link>
      </div>
    </Modal>
  );
}

export default function BriefingPage() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useApi("/api/briefing");
  const [job, setJob] = useState<Json>(null);
  const [old, setOld] = useState<Json>(null);
  const refresh = async () => {
    const j = await api.post("/api/briefing/refresh");
    setJob({ status: "running", id: j.job_id });
    setJob(await waitForJob(j.job_id, setJob));
    reload();
  };
  return (
    <div>
      <PageHead title={t("Daily Briefing")} question={t("What happened today in biotech, animal health and regulation that matters to us?")}
        next={[["/competitors", t("Competitor Intelligence")], ["/regulatory", t("Regulatory Intelligence")]]}>
        <button className="primary" onClick={refresh} disabled={job?.status === "running"}>{job?.status === "running" ? t("Refreshing…") : t("Refresh now")}</button>
        {job && <StatusPill status={job.status} />}
      </PageHead>
      <div className="tiny muted" style={{ marginTop: -10, marginBottom: 10 }}>{t("Shown once per day on first visit (dismissible). Research runs on a schedule or manual refresh — not on every visit.")}</div>
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading />}
      <div className="grid" style={{ gridTemplateColumns: "minmax(0,1fr) 260px" }}>
        <div className="card">{old ? <><button className="link small" onClick={() => setOld(null)}>← {t("back to latest")}</button><BriefingBody data={{ briefing: old, ranking_rule: data?.ranking_rule }} /></> : data && <BriefingBody data={data} />}</div>
        <div className="card">
          <h3>{t("Earlier briefings")}</h3>
          {(data?.history || []).map((h: Json) => (
            <div key={h.id} className="small" style={{ marginBottom: 4 }}>
              <button className="link" onClick={async () => setOld(await api.get(`/api/briefing/${h.id}`))}>{h.briefing_date}</button> <StatusPill status={h.status} />
            </div>
          ))}
          <div className="tiny muted" style={{ marginTop: 10 }}>{t("Automatic refresh needs this computer awake and either the app running (in-app scheduler) or the daily job scheduled with launchd/cron. A closed laptop does not collect updates.")}</div>
        </div>
      </div>
    </div>
  );
}
