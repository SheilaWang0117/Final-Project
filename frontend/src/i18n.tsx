// English / Simplified Chinese UI text.
// Keys are the English strings, so English needs no table and missing
// translations fall back to readable English. Placeholders use {name}.
// The choice is remembered in localStorage and can be set with ?lang=zh / ?lang=en.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ZH } from "./i18n_zh";

export type Lang = "en" | "zh";
type Vars = Record<string, string | number | null | undefined>;

function initialLang(): Lang {
  const q = new URLSearchParams(window.location.search).get("lang");
  if (q === "zh" || q === "en") return q;
  const saved = window.localStorage.getItem("ocra.lang");
  return saved === "zh" ? "zh" : "en";
}

function fill(s: string, vars?: Vars) {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined || vars[k] === null ? "" : String(vars[k])));
}

// Backend status/enum values -> English labels (then translated).
const ENUM: Record<string, string> = {
  in_progress: "In progress", at_risk: "At risk", on_hold: "On hold", needs_review: "Needs review", not_applicable: "Not applicable",
  small_molecule: "Small molecule", missing_balance: "Missing balance", limit_exceeded: "Limit exceeded", invalid_output: "Invalid output",
  blocked_secret: "Blocked (secret)", provider_error: "Provider error", content_filtered: "Content filtered", not_configured: "Not configured",
  manual_only: "Manual only", index_page: "Index page", vet_drug: "Veterinary drugs", vet_biologic: "Veterinary biologics",
  human_drug: "Human drugs", human_biologic: "Human biologics", lead_candidate: "Biotech industry", animal_health: "Animal health",
  therapeutic_species_fit: "Therapeutic and species fit", portfolio_relevance: "Portfolio relevance", geographic_capability: "Geographic capability",
  commercial_capability: "Commercial capability", prior_licensing_activity: "Prior licensing activity", stated_strategic_interest: "Stated strategic interest",
  trial_registration: "Trial registration", trial_status_change: "Trial status change", published_results: "Published results",
  regulatory_submission: "Regulatory submission", regulatory_decision: "Regulatory decision", licensing_deal: "Licensing deal",
  company_announcement: "Company announcement", already_running: "Already running",
};

export function enumLabel(v: string | null | undefined): string {
  if (!v) return "—";
  return ENUM[v] || v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

// Data-quality and system warnings from the backend, by code (Chinese summary; the English detail is kept).
const ISSUE_ZH: Record<string, string> = {
  missing_balance: "有账户缺少已对账余额，现金数据不完整。",
  balance_currency: "账户余额币种与账户币种不一致。",
  txn_currency_mismatch: "部分交易币种与账户币种不一致，未计入该账户。",
  stale_reconciliation: "账户对账已超过 45 天，请更新银行余额。",
  txn_without_account: "部分交易没有账户，不影响现金余额。",
  no_accounts: "尚未设置现金账户。",
  missing_fx: "部分金额缺少汇率，未计入合计。请补充汇率。",
  stale_fx: "部分换算使用了超过 10 天的旧汇率。",
  unmatched_transfers: "部分转账找不到对应的另一笔，请检查是否为外部付款。",
  burn_months_without_data: "所选期间有月份没有交易记录，平均消耗可能被低估。",
  even_spread: "该预算没有未来月度计划，剩余成本平均分摊到里程碑结束。",
  schedule_elapsed: "部分剩余成本没有未来计划或日期，假定本月支付。",
  commitment_overdue_or_undated: "有承付款已逾期或未设日期，假定本月支付。",
  shared_costs_end: "公司共用成本只编制到某个月份，之后的预测不含这些成本。",
  incomplete_cash: "没有完整的已对账现金余额，无法计算预测现金和跑道。",
  beyond_horizon: "部分计划支出落在预测期之后。",
  unallocated_spend: "部分运营支出尚未分配到项目或共用成本池。",
  milestones_without_budget: "有未完成的里程碑没有预算，预测会低估未来成本。",
  no_fx_rates: "尚未记录任何汇率，非报告币种金额无法换算。",
};

type Ctx = { lang: Lang; setLang: (l: Lang) => void };
const LangContext = createContext<Ctx>({ lang: "en", setLang: () => {} });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    window.localStorage.setItem("ocra.lang", l);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = lang === "zh" ? "Ocra 研发管线追踪器" : "Ocra Pipeline Tracker";
  }, [lang]);
  const value = useMemo(() => ({ lang, setLang }), [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useI18n() {
  const { lang, setLang } = useContext(LangContext);
  const t = useCallback((s: string, vars?: Vars) => fill(lang === "zh" ? ZH[s] ?? s : s, vars), [lang]);
  const tl = useCallback((v: string | null | undefined) => (v ? t(enumLabel(v)) : "—"), [t]);
  const issue = useCallback(
    (i: { code?: string; message: string }) => (lang === "zh" && i.code && ISSUE_ZH[i.code] ? ISSUE_ZH[i.code] : i.message),
    [lang],
  );
  return { t, tl, issue, lang, setLang };
}
