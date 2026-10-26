import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, type Json } from "./api";
import { Cat, Dog, Paw } from "./components/pets";
import { I18nProvider, useI18n } from "./i18n";
import Assistant from "./pages/Assistant";
import BriefingPage, { BriefingPopup } from "./pages/Briefing";
import Budget from "./pages/Budget";
import Competitors from "./pages/Competitors";
import Markets from "./pages/Markets";
import Overview from "./pages/Overview";
import Pipelines, { ProgramDetail } from "./pages/Pipelines";
import Regulatory from "./pages/Regulatory";
import Settings from "./pages/Settings";

export const StatusContext = createContext<Json>(null);
export const useStatus = () => useContext(StatusContext);

// Navigation grouped by the question a manager brings to the app.
export const NAV_GROUPS: { title: string; items: { to: string; name: string; hint: string; icon: string }[] }[] = [
  { title: "Start here", items: [{ to: "/", name: "Overview", hint: "Big picture and today's priorities", icon: "⌂" }] },
  { title: "Our science", items: [{ to: "/pipelines", name: "Pipelines", hint: "What we develop and what comes next", icon: "⚗" }] },
  { title: "Our money", items: [{ to: "/budget", name: "Budget and Runway", hint: "Can we afford the next milestone?", icon: "$" }] },
  {
    title: "Outside world",
    items: [
      { to: "/briefing", name: "Daily Briefing", hint: "What is new today?", icon: "☀" },
      { to: "/competitors", name: "Competitor Intelligence", hint: "What are others doing?", icon: "⚑" },
      { to: "/regulatory", name: "Regulatory Intelligence", hint: "Which rules apply to us?", icon: "§" },
      { to: "/markets", name: "Markets and Licensing", hint: "Who could partner with us?", icon: "◎" },
    ],
  },
  {
    title: "Get help",
    items: [
      { to: "/assistant", name: "AI Assistant", hint: "Ask in plain words", icon: "?" },
      { to: "/settings", name: "Settings and Activity", hint: "Setup, usage, audit log", icon: "⚙" },
    ],
  },
];

function findPage(path: string) {
  for (const g of NAV_GROUPS) {
    for (const it of g.items) {
      if (it.to === "/" ? path === "/" : path.startsWith(it.to)) return { group: g.title, item: it };
    }
  }
  return null;
}

function LangToggle() {
  const { lang, setLang } = useI18n();
  return (
    <div className="lang-toggle" role="group" aria-label="Language / 语言">
      <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")} aria-pressed={lang === "en"}>EN</button>
      <button className={lang === "zh" ? "on" : ""} onClick={() => setLang("zh")} aria-pressed={lang === "zh"}>中文</button>
    </div>
  );
}

function ModeBanner({ status }: { status: Json }) {
  const { t } = useI18n();
  if (!status) return null;
  if (status.mode === "demo")
    return (
      <div className="mode-banner mode-demo" role="note">
        <b>{t("Demo mode")}</b> {t("Internal records are synthetic and research items are labeled fixtures. No model calls or live retrieval.")}
        {status.as_of_override && <span>· {t("Fixed as-of date {d}", { d: status.as_of_override })}</span>}
      </div>
    );
  return (
    <div className="mode-banner mode-live" role="note">
      <b>{t("Live mode")}</b> {t("Real public retrieval and model calls ({p}: {m}).", { p: status.provider, m: status.model || "none" })}
      {!status.ready && <span style={{ color: "#b3261e" }}>· {t("Model not ready: {e}", { e: status.errors?.join("; ") || t("API key missing") })}</span>}
      {status.contains_synthetic_data && <span>· {t("This database contains synthetic demo records (labeled).")}</span>}
      {status.as_of_override && <span>· {t("As-of date overridden: {d}", { d: status.as_of_override })}</span>}
    </div>
  );
}

function Shell() {
  const { t } = useI18n();
  const loc = useLocation();
  const [status, setStatus] = useState<Json>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  useEffect(() => {
    api.get("/api/status").then(setStatus).catch((e) => setStatusError(e.message));
  }, []);
  const here = findPage(loc.pathname);
  return (
    <StatusContext.Provider value={status}>
      <div className="layout">
        <aside className="sidebar" aria-label={t("Main navigation")}>
          <div className="sidebar-inner">
            <div className="brand">
              <div className="brand-pets" aria-hidden>
                <Cat size={30} />
                <Dog size={30} />
              </div>
              <div>
                <div className="brand-name">{t("Ocra Pipeline Tracker")}</div>
                <div className="brand-sub">{t("All life matters")}</div>
              </div>
            </div>
            <nav className="nav">
              {NAV_GROUPS.map((g) => (
                <div key={g.title} className="nav-group">
                  <div className="nav-group-title">{t(g.title)}</div>
                  {g.items.map((it) => (
                    <NavLink key={it.to} to={it.to} end={it.to === "/"}>
                      <span className="num" aria-hidden>{it.icon}</span>
                      <span>
                        <span className="nav-name">{t(it.name)}</span>
                        <span className="nav-hint">{t(it.hint)}</span>
                      </span>
                    </NavLink>
                  ))}
                </div>
              ))}
            </nav>
            <div className="side-foot">
              <div className="side-pets" aria-hidden><Paw size={12} color="#5e7a90" /> <Paw size={12} color="#5e7a90" /> <Paw size={12} color="#5e7a90" /></div>
              {t("Local prototype · 127.0.0.1 only")}
              <br />
              {t("Management view, not audited statements.")}
            </div>
          </div>
        </aside>
        <main className="main">
          {statusError && <div className="alert error">{t("Cannot reach the backend: {e}. Start it with the command in the README.", { e: statusError })}</div>}
          <div className="crumbs">
            <span>
              {here ? (
                <>
                  {t("You are here:")} <b>{t(here.group)}</b> › {t(here.item.name)}
                </>
              ) : (
                t("Ocra Pipeline Tracker")
              )}
            </span>
            <LangToggle />
          </div>
          <ModeBanner status={status} />
          <BriefingPopup />
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/pipelines" element={<Pipelines />} />
            <Route path="/pipelines/:id" element={<ProgramDetail />} />
            <Route path="/budget" element={<Budget />} />
            <Route path="/competitors" element={<Competitors />} />
            <Route path="/briefing" element={<BriefingPage />} />
            <Route path="/regulatory" element={<Regulatory />} />
            <Route path="/markets" element={<Markets />} />
            <Route path="/assistant" element={<Assistant />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<p>{t("Page not found.")}</p>} />
          </Routes>
        </main>
      </div>
    </StatusContext.Provider>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <Shell />
    </I18nProvider>
  );
}
