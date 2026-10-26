import { useState, type ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Json } from "../api";
import { money } from "../format";
import { useI18n } from "../i18n";

// Validated categorical slots (fixed order, never cycled).
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
const AXIS = { fontSize: 11, fill: "#737a83" };
const GRID = "#ece9e3";

export function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="legend" aria-hidden>
      {items.map(([name, color]) => (
        <span key={name}>
          <i style={{ background: color }} />
          {name}
        </span>
      ))}
    </div>
  );
}

function Tip({ active, payload, label, ccy, extra, suffix }: Json) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {payload.map((p: Json) => (
        <div className="r" key={p.dataKey}>
          <span>
            <i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: p.color, marginRight: 6 }} />
            {p.name}
          </span>
          <b>{p.value == null ? "—" : ccy ? money(Math.round(p.value * 100), ccy) : `${Number(p.value).toLocaleString(undefined, { maximumFractionDigits: 0 })}${suffix || ""}`}</b>
        </div>
      ))}
      {extra}
    </div>
  );
}

export function ChartMeta({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <div className="chart-meta">
      <dl>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function TableToggle({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="link small" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? t("Hide data table") : t("Show data table")}
      </button>
      {open && <div className="table-wrap" style={{ marginTop: 6, maxHeight: 260 }}>{children}</div>}
    </div>
  );
}

const k = (v: number) => (Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Math.abs(v) >= 1e3 ? `${Math.round(v / 1e3)}K` : `${v}`);

// ------------------------------------------------------------- cash forecast

export function CashForecastChart({ months, reserve, ccy, scenario, scenarioName }: { months: Json[]; reserve: number; ccy: string; scenario?: Json[]; scenarioName?: string }) {
  const { t } = useI18n();
  const data = months.map((m: Json, i: number) => ({
    month: m.month,
    base: m.closing_minor == null ? null : m.closing_minor / 100,
    scenario: scenario ? (scenario[i]?.scenario_closing_minor ?? null) / 100 : undefined,
  }));
  const items: [string, string][] = [[t("Baseline projected cash"), SERIES[0]]];
  if (scenario) items.push([scenarioName || t("Scenario"), SERIES[1]]);
  return (
    <div>
      {scenario && <Legend items={items} />}
      <div style={{ width: "100%", height: 260 }} role="img" aria-label={t("Projected month-end cash")}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis tick={AXIS} tickFormatter={k} tickLine={false} axisLine={false} width={52} />
            <Tooltip content={<Tip ccy={ccy} />} />
            <ReferenceLine y={reserve / 100} stroke="#b3261e" strokeDasharray="4 4" label={{ value: t("minimum reserve"), position: "insideTopRight", fontSize: 11, fill: "#b3261e" }} />
            <ReferenceLine y={0} stroke="#9aa0a6" />
            <Line type="monotone" dataKey="base" name={t("Baseline projected cash")} stroke={SERIES[0]} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls={false} />
            {scenario && <Line type="monotone" dataKey="scenario" name={scenarioName || t("Scenario")} stroke={SERIES[1]} strokeWidth={2} strokeDasharray="6 3" dot={{ r: 3 }} activeDot={{ r: 5 }} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableToggle>
        <table className="t">
          <thead><tr><th>{t("Month")}</th><th className="n">{t("Baseline")}</th>{scenario && <th className="n">{scenarioName}</th>}</tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.month}><td>{d.month}</td><td className="n">{d.base == null ? "—" : money(Math.round(d.base * 100), ccy)}</td>{scenario && <td className="n">{d.scenario == null ? "—" : money(Math.round((d.scenario as number) * 100), ccy)}</td>}</tr>
            ))}
          </tbody>
        </table>
      </TableToggle>
    </div>
  );
}

// ------------------------------------------------------------- monthly burn

export function BurnChart({ series, ccy }: { series: Json[]; ccy: string }) {
  const { t } = useI18n();
  const data = series.map((s: Json) => ({ month: s.month, out: s.outflows / 100, in: s.inflows / 100 }));
  return (
    <div>
      <Legend items={[[t("Operating outflows"), SERIES[0]], [t("Operating inflows (incl. refunds)"), SERIES[1]]]} />
      <div style={{ width: "100%", height: 220 }} role="img" aria-label={t("Monthly operating cash flows")}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }} barGap={2}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis tick={AXIS} tickFormatter={k} tickLine={false} axisLine={false} width={52} />
            <Tooltip content={<Tip ccy={ccy} />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
            <Bar dataKey="out" name={t("Operating outflows")} fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={28} />
            <Bar dataKey="in" name={t("Operating inflows (incl. refunds)")} fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableToggle>
        <table className="t">
          <thead><tr><th>{t("Month")}</th><th className="n">{t("Outflows")}</th><th className="n">{t("Inflows")}</th><th className="n">{t("Net")}</th></tr></thead>
          <tbody>{series.map((s: Json) => <tr key={s.month}><td>{s.month}</td><td className="n">{money(s.outflows, ccy)}</td><td className="n">{money(s.inflows, ccy)}</td><td className="n">{money(s.net, ccy)}</td></tr>)}</tbody>
        </table>
      </TableToggle>
    </div>
  );
}

// ---------------------------------------------------------- budget vs actual

// ------------------------------------------------------------ market charts

export function RevenueChart({ rows }: { rows: Json[] }) {
  const { t } = useI18n();
  const companies = Array.from(new Set(rows.map((r: Json) => r.company))).slice(0, 4) as string[];
  const years = Array.from(new Set(rows.map((r: Json) => r.period.slice(-10, -6) || r.period))).sort() as string[];
  const data = years.map((y) => {
    const d: Json = { year: y };
    for (const c of companies) {
      const r = rows.find((x: Json) => x.company === c && (x.period.slice(-10, -6) || x.period) === y);
      d[c] = r ? Number(r.value) / (r.unit === "USD" ? 1e6 : 1) : null;
    }
    return d;
  });
  return (
    <div>
      <Legend items={companies.map((c, i) => [c, SERIES[i]])} />
      <div style={{ width: "100%", height: 260 }} role="img" aria-label={t("Reported company revenue by fiscal year")}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }} barGap={2}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} tickFormatter={(v) => `${v.toLocaleString()}`} label={{ value: t("USD millions"), angle: -90, position: "insideLeft", fontSize: 11, fill: "#737a83" }} />
            <Tooltip content={<Tip suffix={` ${t("USD M")}`} />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
            {companies.map((c, i) => (
              <Bar key={c} dataKey={c} name={c} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableToggle>
        <table className="t">
          <thead><tr><th>{t("Company")}</th><th>{t("Period")}</th><th className="n">{t("Value")}</th><th>{t("Type")}</th><th>{t("Source")}</th></tr></thead>
          <tbody>{rows.map((r: Json) => <tr key={r.id}><td>{r.company}</td><td>{r.period}</td><td className="n">{Number(r.value).toLocaleString()} {r.unit}</td><td>{r.value_type}</td><td className="small">{r.source_name}</td></tr>)}</tbody>
        </table>
      </TableToggle>
    </div>
  );
}

export function ShareDonut({ rows }: { rows: Json[] }) {
  const { t } = useI18n();
  const data = rows.map((r: Json) => ({ name: r.company, value: Number(r.value) }));
  return (
    <div style={{ width: "100%", height: 240 }} role="img" aria-label={t("Market share")}>
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={60} outerRadius={95} paddingAngle={1} stroke="#fff" strokeWidth={2}>
            {data.slice(0, 4).map((_d, i) => <Cell key={i} fill={SERIES[i]} />)}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
