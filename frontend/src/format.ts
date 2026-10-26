// Display helpers. Money arrives from the API as integer minor units.

export function money(minor: number | null | undefined, ccy = "USD", opts: { compact?: boolean } = {}): string {
  if (minor === null || minor === undefined) return "—";
  const v = minor / 100;
  if (opts.compact && Math.abs(v) >= 1000) {
    const units: [number, string][] = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (const [n, s] of units) if (Math.abs(v) >= n) return `${ccy} ${(v / n).toFixed(Math.abs(v) >= n * 10 ? 0 : 1)}${s}`;
  }
  return `${ccy} ${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function num(v: number | string | null | undefined, digits = 0): string {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function dateOnly(s: string | null | undefined): string {
  return s ? s.slice(0, 10) : "—";
}

export function dateTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ago(s: string | null | undefined, lang: "en" | "zh" = "en"): string {
  const zh = lang === "zh";
  if (!s) return zh ? "从未" : "never";
  const ms = Date.now() - new Date(s).getTime();
  if (isNaN(ms)) return s;
  const h = ms / 3.6e6;
  if (h < 1) return zh ? `${Math.max(1, Math.round(ms / 60000))} 分钟前` : `${Math.max(1, Math.round(ms / 60000))} min ago`;
  if (h < 48) return zh ? `${Math.round(h)} 小时前` : `${Math.round(h)} h ago`;
  return zh ? `${Math.round(h / 24)} 天前` : `${Math.round(h / 24)} days ago`;
}

export function toMinor(input: string): number {
  return Math.round(parseFloat(input.replace(/,/g, "")) * 100);
}

export const label = (s: string | null | undefined) => (s ? s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—");
