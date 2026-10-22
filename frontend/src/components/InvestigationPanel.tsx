import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type { ExceptionDetail, InvestigationSummary } from "../api/types";
import { analystIdProblem, useAnalyst } from "../lib/analyst";
import { durationText, formatDateTime, humanize } from "../lib/format";
import { useElapsed, useLoad } from "../lib/hooks";
import { AiReportView } from "./AiReport";
import { Card, Empty, ErrorBox, Icon, Loading } from "./common";

const CLOSED = new Set(["RESOLVED", "REJECTED"]);

export function InvestigationPanel({
  exception, onChanged, onOpenEvidence,
}: {
  exception: ExceptionDetail;
  onChanged: () => void;
  onOpenEvidence: (id: string) => void;
}) {
  const { analystId } = useAnalyst();
  const id = exception.exception_id;
  const aiStatus = useLoad(() => api.aiStatus(), []);
  const list = useLoad(() => api.investigations(id), [id]);
  const [selected, setSelected] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<ApiError | null>(null);
  const elapsed = useElapsed(running);

  // Default selection: latest successful investigation, else the latest one.
  useEffect(() => {
    const items = list.data ?? [];
    if (items.length === 0) {
      setSelected(null);
      return;
    }
    if (selected && items.some((i) => i.investigation_id === selected)) return;
    setSelected((items.find((i) => i.status === "SUCCEEDED") ?? items[0]).investigation_id);
  }, [list.data, selected]);

  const detail = useLoad(() => (selected ? api.investigation(selected) : Promise.resolve(undefined)), [selected]);

  const typesById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const item of detail.data?.evidence_package.items ?? []) map[item.evidence_id] = item.evidence_type;
    return map;
  }, [detail.data]);

  const actorProblem = analystIdProblem(analystId);
  const ollamaProblem =
    aiStatus.data && !aiStatus.data.model_available ? aiStatus.data.error ?? "The configured model is not available." : null;
  const closed = CLOSED.has(exception.status);
  const disabledReason = closed ? `The exception is ${exception.status.toLowerCase()}.` : actorProblem ?? ollamaProblem;

  async function run() {
    setRunning(true);
    setRunError(null);
    try {
      const created = await api.investigate(id, analystId.trim());
      setSelected(created.investigation_id);
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : new ApiError(String(err));
      setRunError(apiErr);
      if (apiErr.reference) setSelected(apiErr.reference);
    } finally {
      setRunning(false);
      list.reload();
      onChanged();
    }
  }

  const runs = list.data ?? [];
  const succeededCount = runs.filter((r) => r.status === "SUCCEEDED").length;

  return (
    <div className="stack">
      <section className="card ai-launch">
        <div className="ai-launch-main">
          <span className="ai-launch-icon"><Icon name="spark" size={22} /></span>
          <div>
            <h2>AI investigation</h2>
            <p className="muted small">
              Drafts a likely explanation from this exception's evidence package. Every claim cites evidence you can open.
              The AI suggests; you decide.
            </p>
          </div>
          <button type="button" className="btn-ai btn-lg" disabled={running || Boolean(disabledReason)} onClick={() => void run()}
                  title={disabledReason ?? undefined}>
            <Icon name="spark" /> {running ? `Investigating… ${elapsed}s` : runs.length ? "Run again" : "Run AI investigation"}
          </button>
        </div>
        {running && (
          <div className="ai-progress" role="status">
            <div className="ai-progress-bar"><span /></div>
            <p className="small muted">
              Analysing the evidence. On a laptop CPU this usually takes 2–6 minutes. If the first answer fails validation,
              one corrective retry is made automatically.
            </p>
          </div>
        )}
        {disabledReason && !running && <p className="hint">{disabledReason}</p>}
        <ErrorBox error={runError} title="Investigation did not produce a valid report" />
      </section>

      <Card title={<>Investigation history <span className="rsec-count">{runs.length}</span></>}
            actions={runs.length > 0 ? <span className="small muted">{succeededCount} report(s) · {runs.length - succeededCount} failed</span> : undefined}>
        {list.loading && !list.data && <Loading />}
        <ErrorBox error={list.error} />
        {list.data && runs.length === 0 && <Empty>No AI investigation has been run for this exception yet.</Empty>}
        {runs.length > 0 && (
          <ul className="run-list">
            {runs.map((inv: InvestigationSummary) => {
              const ok = inv.status === "SUCCEEDED";
              const isSelected = inv.investigation_id === selected;
              return (
                <li key={inv.investigation_id}>
                  <button type="button" className={`run ${ok ? "run-ok" : "run-failed"} ${isSelected ? "run-selected" : ""}`}
                          aria-pressed={isSelected} onClick={() => setSelected(inv.investigation_id)}>
                    <span className="run-status"><Icon name={ok ? "check" : "x"} /></span>
                    <span className="run-id mono">{inv.investigation_id}</span>
                    <span className="run-result">{ok ? "Report produced" : `Failed · ${inv.error_code ? humanize(inv.error_code) : "error"}`}</span>
                    <span className="run-meta"><Icon name="user" /> {inv.requested_by}</span>
                    <span className="run-meta"><Icon name="clock" /> {durationText(inv.duration_ms)} · {inv.attempts} attempt{inv.attempts === 1 ? "" : "s"}</span>
                    <span className="run-date">{formatDateTime(inv.started_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {selected && (
        <Card title={`Report ${selected}`} provenance="ai" className="ai-card report-card">
          {detail.loading && <Loading what="Loading report" />}
          <ErrorBox error={detail.error} />
          {detail.data && detail.data.report && (
            <AiReportView report={detail.data.report} typesById={typesById} onOpenEvidence={onOpenEvidence} />
          )}
          {detail.data && !detail.data.report && (
            <div>
              <ErrorBox error={new ApiError(detail.data.error_message ?? "No report", undefined, detail.data.error_code ?? undefined)}
                        title="This investigation failed; no recommendation was produced." />
              {detail.data.validation_errors.map((attempt) => (
                <details key={attempt.attempt}>
                  <summary>Attempt {attempt.attempt}: {attempt.errors.length} validation error(s)</summary>
                  <ul className="plain small">{attempt.errors.map((e) => <li key={e}>{e}</li>)}</ul>
                </details>
              ))}
            </div>
          )}
          {detail.data && detail.data.raw_responses.length > 0 && (
            <details className="small">
              <summary>Raw model output ({detail.data.raw_responses.length} attempt(s)) · prompt SHA-256 {detail.data.prompt_sha256.slice(0, 12)}…</summary>
              {detail.data.raw_responses.map((raw, i) => <pre key={i} className="raw">{raw}</pre>)}
            </details>
          )}
        </Card>
      )}
    </div>
  );
}
