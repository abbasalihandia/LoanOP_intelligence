import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { ValidationRun } from "../api/types";
import { Card, Empty, ErrorBox, Loading, SeverityBadge, StatusBadge } from "../components/common";
import { formatDateTime, humanize } from "../lib/format";
import { detailHref, useLoad } from "../lib/hooks";

const STATUSES = ["OPEN", "UNDER_INVESTIGATION", "AWAITING_EVIDENCE", "RECOMMENDATION_GENERATED", "ESCALATED", "RESOLVED", "REJECTED"];
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function ExceptionListPage() {
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  const [loanId, setLoanId] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [version, setVersion] = useState(0);
  const [runResult, setRunResult] = useState<ValidationRun | null>(null);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const [running, setRunning] = useState(false);

  const counts = useLoad(() => api.exceptionCounts(), [version]);
  const list = useLoad(
    () => api.exceptions({ status, severity, category, loan_id: loanId.trim(), active_only: activeOnly }),
    [status, severity, category, loanId, activeOnly, version],
  );

  async function runValidation() {
    setRunning(true);
    setRunError(null);
    try {
      setRunResult(await api.runValidation());
      setVersion((v) => v + 1);
    } catch (err) {
      setRunError(err instanceof ApiError ? err : new ApiError(String(err)));
    } finally {
      setRunning(false);
    }
  }

  const c = counts.data;
  const categories = Object.keys(c?.by_category ?? {}).sort();

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Exception dashboard</h1>
          <p className="lede">Discrepancies between the simulated origination (nCino) and servicing (Loan IQ) systems.</p>
        </div>
        <button type="button" onClick={() => void runValidation()} disabled={running}>
          {running ? "Validating…" : "Run validation"}
        </button>
      </div>

      {runResult && (
        <p className="notice">
          Validation {runResult.run_id}: {runResult.loans_evaluated} loans, {runResult.findings} findings —{" "}
          {runResult.created} new, {runResult.redetected} re-detected, {runResult.suppressed} suppressed,{" "}
          {runResult.no_longer_detected} no longer detected.
        </p>
      )}
      <ErrorBox error={runError} />

      <div className="kpis">
        <Kpi label="Active exceptions" value={c?.active} />
        <Kpi label="Critical" value={c?.by_severity.CRITICAL ?? 0} tone="critical" />
        <Kpi label="High" value={c?.by_severity.HIGH ?? 0} tone="high" />
        <Kpi label="AI report awaiting review" value={c?.by_status.RECOMMENDATION_GENERATED ?? 0} tone="ai" />
        <Kpi label="No longer detected" value={c?.active_no_longer_detected} hint="Still open: closing is an analyst decision" />
        <Kpi label="Resolved" value={c?.by_status.RESOLVED ?? 0} tone="ok" />
      </div>

      <Card title="Exceptions">
        <div className="filters">
          <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
          <select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">All severities</option>
            {SEVERITIES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
          <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </select>
          <input aria-label="Loan ID" placeholder="Loan ID, e.g. LN-1001" value={loanId} onChange={(e) => setLoanId(e.target.value)} />
          <label className="checkbox inline">
            <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} /> Active only
          </label>
        </div>

        {list.loading && !list.data && <Loading what="Loading exceptions" />}
        <ErrorBox error={list.error} />
        {list.data && list.data.length === 0 && <Empty>No exceptions match these filters. Seed the data and run validation if this is a fresh database.</Empty>}
        {list.data && list.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Exception</th><th>Loan</th><th>Rule</th><th>Category</th><th>Severity</th><th>Status</th>
                  <th>Discrepancy</th><th>Last detected</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((e) => (
                  <tr key={e.exception_id} className="clickable" onClick={() => { window.location.hash = detailHref(e.exception_id); }}>
                    <td><a href={detailHref(e.exception_id)} className="mono">{e.exception_id}</a></td>
                    <td className="mono">{e.loan_id}</td>
                    <td className="mono small">{e.rule_id}</td>
                    <td>{humanize(e.category)}</td>
                    <td><SeverityBadge severity={e.severity} /></td>
                    <td>
                      <StatusBadge status={e.status} />
                      {!e.still_detected && <span className="badge no-longer" title="Not found in the latest validation run">not detected</span>}
                    </td>
                    <td className="small">
                      {e.field_name}: <strong>{e.source_value ?? "—"}</strong> → <strong>{e.target_value ?? "—"}</strong>
                    </td>
                    <td className="small">{formatDateTime(e.last_detected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Kpi({ label, value, tone = "", hint }: { label: string; value: number | undefined; tone?: string; hint?: string }) {
  return (
    <div className={`kpi ${tone ? `kpi-${tone}` : ""}`} title={hint}>
      <span className="kpi-value">{value ?? "–"}</span>
      <span className="kpi-label">{label}</span>
    </div>
  );
}
