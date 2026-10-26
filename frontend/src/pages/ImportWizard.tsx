import { useState } from "react";
import { api, type Json } from "../api";
import { Badge, Empty, ErrorBox, Loading, StatusPill, useApi } from "../components/ui";
import { dateTime, money } from "../format";
import { useI18n } from "../i18n";

const STEPS = ["Upload", "Sheet and preview", "Map columns", "Validate and review", "Reconcile", "Commit"];
const FIELD_LABELS: Record<string, string> = {
  txn_date: "Date *", amount: "Amount (signed)", debit: "Debit (money out)", credit: "Credit (money in)", currency: "Currency", direction: "Direction",
  counterparty: "Counterparty", description: "Description", category: "Category", program: "Program", milestone: "Milestone", legal_entity: "Legal entity",
  account: "Account", kind: "Flow type", reference: "Reference",
};

export default function ImportWizard({ onCommitted }: { onCommitted: () => void }) {
  const { t, tl } = useI18n();
  const [step, setStep] = useState(0);
  const [up, setUp] = useState<Json>(null);
  const [batch, setBatch] = useState<Json>(null);
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [header, setHeader] = useState(1);
  const [opts, setOpts] = useState<Json>({ default_currency: "", date_preference: "dmy", sign_convention: "negative_is_outflow", default_account_id: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [stmt, setStmt] = useState<Json>({ account_id: "", opening: "", closing: "" });
  const [recon, setRecon] = useState<Json>(null);
  const accounts = useApi("/api/finance/accounts");
  const programs = useApi("/api/programs");
  const history = useApi("/api/imports");
  const ref = useApi("/api/reference");

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e: Json) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const onFile = (f: File | undefined) =>
    f && run(async () => {
      const r = await api.upload("/api/imports", f);
      setUp(r);
      setBatch(r.batch);
      setMapping(r.batch.mapping);
      setStep(1);
    });
  const chooseSheet = (sheet: string) =>
    run(async () => {
      const r = await api.post(`/api/imports/${batch.id}/configure`, { sheet, header_row: 1, mapping: null, options: {} });
      setBatch(r.batch);
      setMapping(r.batch.mapping);
      setUp({ ...up, preview: r.preview });
    });
  const validate = () =>
    run(async () => {
      const options: Json = { ...opts };
      if (!options.default_currency) delete options.default_currency;
      if (!options.default_account_id) delete options.default_account_id;
      const r = await api.post(`/api/imports/${batch.id}/configure`, { header_row: header, mapping, options });
      setBatch({ ...r.batch, staged: r.staged });
      setStep(3);
    });
  const editRow = (rowId: number, patch: Json) =>
    run(async () => {
      const r = await api.patch(`/api/imports/${batch.id}/rows/${rowId}`, patch);
      setBatch({ ...batch, summary: r.summary, staged: batch.staged.map((s: Json) => (s.id === rowId ? r.row : s)) });
    });
  const reconcile = () =>
    run(async () => {
      setRecon(await api.post(`/api/imports/${batch.id}/reconcile`, { account_id: Number(stmt.account_id), opening: stmt.opening, closing: stmt.closing }));
    });
  const commit = () =>
    run(async () => {
      const r = await api.post(`/api/imports/${batch.id}/commit`, { confirm: true });
      setBatch({ ...batch, ...r.batch });
      setStep(5);
      history.reload();
      onCommitted();
    });
  const reverse = (bid: number) => {
    const reason = window.prompt(t("Reason for reversing this import batch (kept in the audit log):"));
    if (reason && reason.length >= 3) run(async () => { await api.post(`/api/imports/${bid}/reverse`, { reason }); history.reload(); onCommitted(); });
  };

  const preview: string[][] = up?.preview || [];
  const headers = preview[header - 1] || [];
  const staged: Json[] = batch?.staged || [];
  const shown = staged.filter((s) =>
    filter === "all" ? true : filter === "issues" ? s.issues.some((i: Json) => ["error", "warning", "duplicate"].includes(i.level)) : filter === "included" ? s.decision === "include" : s.decision === "skip");
  const summary = batch?.summary;
  const progOpts = (programs.data || []) as Json[];
  const FILTERS: [string, string][] = [["all", t("All")], ["issues", t("Issues")], ["included", t("Included")], ["skipped", t("Skipped")]];

  return (
    <div>
      <ol className="row" style={{ listStyle: "none", padding: 0, margin: "0 0 14px", gap: 6 }} aria-label={t("Import steps")}>
        {STEPS.map((s, i) => (
          <li key={s}><Badge tone={i === step ? "good" : "neutral"}>{i < step ? "✓" : i + 1} {t(s)}</Badge></li>
        ))}
      </ol>
      {err && <ErrorBox error={err} />}
      {busy && <Loading text={t("Working…")} />}

      {step === 0 && (
        <div className="card">
          <h3>{t("1. Upload a CSV or XLSX file")}</h3>
          <p className="small muted">{t("Max 5 MB, 5,000 rows. Formulas are never evaluated and macros never run; macro-enabled workbooks are rejected. Nothing is saved to the ledger until you confirm the final step.")}</p>
          <input type="file" accept=".csv,.xlsx" aria-label={t("Choose file to import")} onChange={(e) => onFile(e.target.files?.[0])} />
          <div className="row small" style={{ marginTop: 10 }}>
            {t("Templates:")} <a href="/api/imports/templates/transactions_template.csv">{t("CSV template")}</a> · <a href="/api/imports/templates/transactions_template.xlsx">{t("XLSX template")}</a> ·
            {t("Synthetic samples:")} <a href="/api/imports/templates/synthetic_ledger_multi_entity.xlsx">{t("multi-entity ledger (XLSX)")}</a> · <a href="/api/imports/templates/synthetic_bank_export_hkd.csv">{t("HKD bank export (CSV)")}</a>
          </div>
        </div>
      )}

      {step >= 1 && step < 5 && up && (
        <div className="card">
          <div className="card-head">
            <h3>{t("2. Sheet and preview · {f}", { f: batch.filename })}</h3>
            <span className="tiny muted">SHA-256 {batch.file_sha256?.slice(0, 12)}…</span>
          </div>
          {up.warnings?.map((w: string) => <div key={w} className="alert warning">! {w}</div>)}
          {batch.sheets?.length > 0 && (
            <label className="f" style={{ maxWidth: 260 }}>{t("Worksheet")}
              <select value={batch.sheet_name} onChange={(e) => chooseSheet(e.target.value)}>{batch.sheets.map((s: string) => <option key={s}>{s}</option>)}</select>
            </label>
          )}
          <label className="f" style={{ maxWidth: 160, marginTop: 6 }}>{t("Header row")}<input type="number" min={1} value={header} onChange={(e) => setHeader(Number(e.target.value))} /></label>
          <div className="table-wrap" style={{ marginTop: 8, maxHeight: 220 }}>
            <table className="t"><tbody>{preview.slice(0, 12).map((r, i) => <tr key={i} style={i === header - 1 ? { fontWeight: 700 } : {}}><td className="muted">{i + 1}</td>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
          </div>
          {step === 1 && <button className="primary" style={{ marginTop: 8 }} onClick={() => setStep(2)}>{t("Next: map columns")}</button>}
        </div>
      )}

      {step >= 2 && step < 5 && (
        <div className="card">
          <h3>{t("3. Map columns and options")}</h3>
          <div className="form-grid">
            {up.fields.map((f: string) => (
              <label key={f} className="f">{t(FIELD_LABELS[f] || f)}
                <select value={mapping[f] ?? ""} onChange={(e) => { const m = { ...mapping }; if (e.target.value === "") delete m[f]; else m[f] = Number(e.target.value); setMapping(m); }}>
                  <option value="">{t("— not in file —")}</option>
                  {headers.map((h, i) => <option key={i} value={i}>{h || t("(column {n})", { n: i + 1 })}</option>)}
                </select>
              </label>
            ))}
          </div>
          <div className="form-grid" style={{ marginTop: 10 }}>
            <label className="f">{t("Default currency (only for rows without one)")}<select value={opts.default_currency} onChange={(e) => setOpts({ ...opts, default_currency: e.target.value })}><option value="">{t("none — flag missing")}</option>{(ref.data?.currencies || []).map((c: string) => <option key={c}>{c}</option>)}</select></label>
            <label className="f">{t("Ambiguous dates like 04/07/2026")}<select value={opts.date_preference} onChange={(e) => setOpts({ ...opts, date_preference: e.target.value })}><option value="dmy">{t("day/month/year (flagged)")}</option><option value="mdy">{t("month/day/year (flagged)")}</option></select></label>
            <label className="f">{t("Amount sign")}<select value={opts.sign_convention} onChange={(e) => setOpts({ ...opts, sign_convention: e.target.value })}><option value="negative_is_outflow">{t("negative = money out")}</option><option value="positive_is_outflow">{t("positive = money out")}</option></select></label>
            <label className="f">{t("Default account (if no account column)")}<select value={opts.default_account_id} onChange={(e) => setOpts({ ...opts, default_account_id: e.target.value })}><option value="">{t("none")}</option>{(accounts.data?.accounts || []).map((a: Json) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
          </div>
          <button className="primary" style={{ marginTop: 10 }} disabled={busy} onClick={validate}>{step >= 3 ? t("Re-validate") : t("Validate")}</button>
        </div>
      )}

      {step >= 3 && step < 5 && summary && (
        <div className="card">
          <div className="card-head">
            <h3>{t("4. Review rows · {a} of {b} will be imported", { a: summary.rows_included, b: summary.rows_total })}</h3>
            <div className="row small">
              {FILTERS.map(([f, name]) => <button key={f} className={filter === f ? "primary" : ""} onClick={() => setFilter(f)}>{name}</button>)}
            </div>
          </div>
          <div className="row small" style={{ marginBottom: 8 }}>
            <Badge tone="bad">✕ {t("{n} with errors", { n: summary.rows_with_errors })}</Badge><Badge tone="warn">! {t("{n} with warnings", { n: summary.rows_with_warnings })}</Badge><Badge tone="warn">⧉ {t("{n} duplicates", { n: summary.rows_duplicate })}</Badge>
            <span className="muted">{t("Suggestions are rule-based (keywords, program codes, counterparty history). Review before committing.")}</span>
          </div>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table className="t">
              <thead><tr><th>{t("Row")}</th><th>{t("Include")}</th><th>{t("Date")}</th><th className="n">{t("Amount")}</th><th>{t("Flow type")}</th><th>{t("Description")}</th><th>{t("Category")}</th><th>{t("Program")}</th><th>{t("Allocation")}</th><th>{t("Issues")}</th></tr></thead>
              <tbody>
                {shown.map((s) => {
                  const p = s.parsed;
                  return (
                    <tr key={s.id}>
                      <td className="muted">{s.sheet_row}</td>
                      <td><input type="checkbox" aria-label={t("Include row {n}", { n: s.sheet_row })} checked={s.decision === "include"} disabled={!p} onChange={(e) => editRow(s.id, { decision: e.target.checked ? "include" : "skip" })} /></td>
                      <td className="small">{p?.txn_date || "—"}</td>
                      <td className="n">{p ? <span style={{ color: p.direction === "outflow" ? "var(--ink)" : "var(--good)" }}>{p.direction === "outflow" ? "−" : "+"}{money(p.amount_minor, p.currency)}</span> : "—"}</td>
                      <td>{p ? <select value={p.kind} onChange={(e) => editRow(s.id, { kind: e.target.value })} aria-label={t("Flow type")}>{["operating", "refund", "financing", "transfer"].map((k) => <option key={k} value={k}>{tl(k)}</option>)}</select> : "—"}</td>
                      <td className="small" style={{ maxWidth: 240 }}>{p?.description || s.raw?.[mapping.description] || "—"}<div className="tiny muted">{p?.counterparty}</div></td>
                      <td>{p ? <select value={p.category || ""} onChange={(e) => editRow(s.id, { category: e.target.value || null })} aria-label={t("Category")}><option value="">—</option>{(ref.data?.categories || []).map((c: string) => <option key={c} value={c}>{t(c)}</option>)}</select> : "—"}</td>
                      <td>{p ? <select value={p.program_id ?? ""} onChange={(e) => editRow(s.id, e.target.value ? { program_id: Number(e.target.value) } : { program_id: null, allocation: "unallocated" })} aria-label={t("Program")}><option value="">—</option>{progOpts.map((x) => <option key={x.id} value={x.id}>{x.code}</option>)}</select> : "—"}</td>
                      <td>{p ? <select value={p.allocation} onChange={(e) => editRow(s.id, { allocation: e.target.value })} aria-label={t("Allocation")}>{["direct", "shared", "unallocated"].map((a) => <option key={a} value={a}>{tl(a)}</option>)}</select> : "—"}</td>
                      <td className="small" style={{ maxWidth: 280 }}>
                        {s.issues.map((i: Json, k: number) => <div key={k} style={{ color: i.level === "error" ? "var(--bad)" : i.level === "info" ? "var(--ink-3)" : "var(--warn)" }}>{i.level === "error" ? "✕" : i.level === "duplicate" ? "⧉" : i.level === "info" ? "i" : "!"} {i.message}</div>)}
                        {p?.commitment_id && <div><button className="link tiny" onClick={() => editRow(s.id, { clear_commitment: true })}>{t("unlink commitment #{n}", { n: p.commitment_id })}</button></div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {step === 3 && <button className="primary" style={{ marginTop: 10 }} onClick={() => setStep(4)}>{t("Next: reconciliation summary")}</button>}
        </div>
      )}

      {step === 4 && summary && (
        <div className="card">
          <h3>{t("5. Reconciliation summary")}</h3>
          <div className="grid g2">
            <div>
              <table className="t">
                <tbody>
                  <tr><td>{t("Rows in file")}</td><td className="n">{summary.rows_total}</td></tr>
                  <tr><td>{t("To import")}</td><td className="n">{summary.rows_included}</td></tr>
                  <tr><td>{t("Skipped (errors, duplicates, or by you)")}</td><td className="n">{summary.rows_skipped}</td></tr>
                  <tr><td>{t("Date range")}</td><td className="n">{summary.date_range?.join(" → ") || "—"}</td></tr>
                </tbody>
              </table>
              <div className="section-label">{t("Totals by currency, flow type, direction (never combined across currencies)")}</div>
              <table className="t">
                <tbody>{summary.totals.map((x: Json) => {
                  const [ccy, kind, dir] = x.group.split(" ");
                  return <tr key={x.group}><td>{ccy} · {tl(kind)} · {tl(dir)}</td><td className="n">{x.count}</td><td className="n">{money(x.amount_minor, ccy)}</td></tr>;
                })}</tbody>
              </table>
              {Object.keys(summary.unallocated_minor_by_currency).length > 0 && (
                <div className="alert warning">! {t("Unallocated operating amounts: {a}. They stay visible as unallocated; nothing is assigned arbitrarily.", { a: Object.entries(summary.unallocated_minor_by_currency).map(([c, v]) => money(v as number, c)).join(", ") })}</div>
              )}
            </div>
            <div>
              <div className="section-label">{t("Optional bank-statement check")}</div>
              <div className="form-grid">
                <label className="f">{t("Account")}<select value={stmt.account_id} onChange={(e) => setStmt({ ...stmt, account_id: e.target.value })}><option value="">—</option>{(accounts.data?.accounts || []).map((a: Json) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
                <label className="f">{t("Statement opening")}<input value={stmt.opening} onChange={(e) => setStmt({ ...stmt, opening: e.target.value })} /></label>
                <label className="f">{t("Statement closing")}<input value={stmt.closing} onChange={(e) => setStmt({ ...stmt, closing: e.target.value })} /></label>
              </div>
              <button style={{ marginTop: 6 }} disabled={!stmt.account_id} onClick={reconcile}>{t("Check movement")}</button>
              {recon?.statement_check && (
                <div className={`alert ${recon.statement_check.reconciled ? "good" : "warning"}`}>
                  {recon.statement_check.reconciled ? `✓ ${t("Imported movement matches the statement.")}` : `! ${t("Difference: {d} (imported {i} vs statement {s}).", { d: (recon.statement_check.difference_minor / 100).toLocaleString(), i: (recon.statement_check.imported_movement_minor / 100).toLocaleString(), s: (recon.statement_check.expected_movement_minor / 100).toLocaleString() })}`}
                </div>
              )}
              <div className="alert info" style={{ marginTop: 10 }}>i {t("Importing transactions does not set the cash balance. Cash comes from reconciled balances plus later transactions on each account.")}</div>
            </div>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" disabled={busy || summary.rows_included === 0} onClick={commit}>{t("Confirm and import {n} transactions", { n: summary.rows_included })}</button>
            <button onClick={() => setStep(3)}>{t("Back to review")}</button>
            <button className="danger" onClick={() => run(async () => { await api.post(`/api/imports/${batch.id}/discard`); setStep(0); setUp(null); setBatch(null); })}>{t("Discard")}</button>
          </div>
        </div>
      )}

      {step === 5 && batch && (
        <div className="card">
          <div className="alert good">✓ {t("Imported {n} transactions (batch #{b}).", { n: batch.summary.committed_transactions, b: batch.id })} {batch.summary.commitments_marked_paid ? t("{n} commitment(s) marked paid.", { n: batch.summary.commitments_marked_paid }) : ""} {batch.summary.skipped_duplicates_at_commit ? t("{n} duplicate(s) skipped.", { n: batch.summary.skipped_duplicates_at_commit }) : ""}</div>
          <button onClick={() => { setStep(0); setUp(null); setBatch(null); }}>{t("Import another file")}</button>
        </div>
      )}

      <div className="card">
        <h3>{t("Import history")}</h3>
        {history.data?.length === 0 && <Empty title={t("No imports yet")} />}
        {history.data?.length > 0 && (
          <table className="t">
            <thead><tr><th>#</th><th>{t("File")}</th><th>{t("Sheet")}</th><th>{t("Uploaded")}</th><th>{t("Status")}</th><th className="n">{t("Transactions")}</th><th /></tr></thead>
            <tbody>
              {history.data.map((b: Json) => (
                <tr key={b.id}>
                  <td>{b.id}</td><td>{b.filename}</td><td>{b.sheet_name || "—"}</td><td className="small">{dateTime(b.created_at)}</td>
                  <td><StatusPill status={b.status} />{b.reverse_reason && <div className="tiny muted">{b.reverse_reason}</div>}</td>
                  <td className="n">{b.transactions}</td>
                  <td>{b.status === "committed" && <button className="danger small" onClick={() => reverse(b.id)}>{t("Reverse batch")}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="tiny muted">{t("Reversal flags the batch's transactions as reversed (excluded from calculations) and keeps them for audit.")}</div>
      </div>
    </div>
  );
}
