import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type { EvidencePackage, ExceptionDetail, Option, Resolution } from "../api/types";
import { analystIdProblem, useAnalyst } from "../lib/analyst";
import { formatDateTime, humanize } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { Card, Empty, ErrorBox, EvidenceChips, Loading } from "./common";

export function ResolutionPanel({
  exception, pkg, onChanged, onOpenEvidence,
}: {
  exception: ExceptionDetail;
  pkg: EvidencePackage | undefined;
  onChanged: () => void;
  onOpenEvidence: (id: string) => void;
}) {
  if (exception.status === "RESOLVED") {
    return <ResolutionView exceptionId={exception.exception_id} onOpenEvidence={onOpenEvidence} />;
  }
  if (exception.status === "REJECTED") {
    return <Card title="Resolution"><Empty>This exception was rejected; there is nothing to resolve.</Empty></Card>;
  }
  if (!exception.can_resolve) {
    return (
      <Card title="Resolution">
        <Empty>
          Resolution is available once the exception is under investigation. Use the status controls on the Overview tab
          to move it to <strong>Under investigation</strong> (current status: {humanize(exception.status)}).
        </Empty>
      </Card>
    );
  }
  return <ResolutionForm exception={exception} pkg={pkg} onChanged={onChanged} />;
}

// --- Form ------------------------------------------------------------------------

function Select({ id, label, value, options, onChange }: {
  id: string; label: string; value: string; options: Option[]; onChange: (v: string) => void;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select…</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function ResolutionForm({ exception, pkg, onChanged }: {
  exception: ExceptionDetail; pkg: EvidencePackage | undefined; onChanged: () => void;
}) {
  const id = exception.exception_id;
  const { analystId } = useAnalyst();
  const options = useLoad(() => api.resolutionOptions(), []);
  const investigations = useLoad(() => api.investigations(id), [id]);
  const succeeded = useMemo(() => (investigations.data ?? []).filter((i) => i.status === "SUCCEEDED"), [investigations.data]);

  const [decision, setDecision] = useState("");
  const [investigationId, setInvestigationId] = useState("");
  const [causeIndex, setCauseIndex] = useState<number | null>(null);
  const [category, setCategory] = useState("");
  const [rootCause, setRootCause] = useState("");
  const [recordInError, setRecordInError] = useState("");
  const [outcome, setOutcome] = useState("");
  const [finalAction, setFinalAction] = useState("");
  const [evidence, setEvidence] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const usesAi = decision !== "" && decision !== "NO_AI_REPORT";
  const picksCause = decision === "AI_ACCEPTED" || decision === "AI_MODIFIED";

  useEffect(() => {
    if (usesAi && !investigationId && succeeded.length > 0) setInvestigationId(succeeded[0].investigation_id);
    if (!usesAi) setInvestigationId("");
    if (!picksCause) setCauseIndex(null);
  }, [usesAi, picksCause, investigationId, succeeded]);

  const report = useLoad(
    () => (usesAi && investigationId ? api.investigation(investigationId) : Promise.resolve(undefined)),
    [usesAi, investigationId],
  );
  const causes = report.data?.report?.probable_causes ?? [];

  const actorProblem = analystIdProblem(analystId);
  const missing: string[] = [];
  if (!decision) missing.push("decision");
  if (usesAi && !investigationId) missing.push("AI report");
  if (picksCause && causeIndex === null) missing.push("AI cause");
  if (!category) missing.push("root-cause category");
  if (rootCause.trim().length < 10) missing.push("confirmed root cause (≥ 10 characters)");
  if (!recordInError) missing.push("record in error");
  if (!outcome) missing.push("outcome");
  if (finalAction.trim().length < 5) missing.push("final action");
  if (evidence.length === 0) missing.push("at least one evidence item");

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.resolve(id, {
        resolved_by: analystId.trim(),
        analyst_decision: decision,
        ai_investigation_id: usesAi ? investigationId : null,
        ai_cause_index: picksCause ? causeIndex : null,
        root_cause_category: category,
        confirmed_root_cause: rootCause.trim(),
        record_in_error: recordInError,
        final_action: finalAction.trim(),
        outcome,
        evidence_ids: evidence,
        notes: notes.trim() || null,
      });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(String(err)));
    } finally {
      setBusy(false);
    }
  }

  if (options.loading || investigations.loading) return <Card title="Resolve exception"><Loading /></Card>;
  const opts = options.data;
  if (!opts) return <Card title="Resolve exception"><ErrorBox error={options.error} /></Card>;

  return (
    <Card title="Resolve exception" provenance="analyst">
      <p className="muted small">
        Your decision is recorded separately from any AI recommendation. Resolving does not change loan records,
        mappings or bookings; corrections are made in the source systems under their own controls.
      </p>

      <fieldset className="field">
        <legend>How did you use the AI recommendation?</legend>
        {opts.analyst_decision.map((o) => {
          const needsReport = o.value !== "NO_AI_REPORT";
          const unavailable = needsReport && succeeded.length === 0;
          return (
            <label key={o.value} className={`radio ${unavailable ? "disabled" : ""}`}>
              <input type="radio" name="decision" value={o.value} checked={decision === o.value}
                     disabled={unavailable} onChange={() => setDecision(o.value)} />
              {o.label}{unavailable && <span className="muted small"> (no AI report available)</span>}
            </label>
          );
        })}
      </fieldset>

      {usesAi && (
        <div className="ai-pick">
          <div className="field">
            <label htmlFor="res-inv">AI report reviewed</label>
            <select id="res-inv" value={investigationId} onChange={(e) => { setInvestigationId(e.target.value); setCauseIndex(null); }}>
              {succeeded.map((i) => (
                <option key={i.investigation_id} value={i.investigation_id}>
                  {i.investigation_id} · {formatDateTime(i.started_at)}
                </option>
              ))}
            </select>
          </div>
          {picksCause && (
            <fieldset className="field">
              <legend>Which AI probable cause?</legend>
              {report.loading && <Loading what="Loading report" />}
              {causes.map((c, i) => (
                <label key={i} className="radio">
                  <input type="radio" name="cause" checked={causeIndex === i} onChange={() => setCauseIndex(i)} />
                  <span>{c.cause} <span className="muted small">({humanize(c.claim_type)}, {c.confidence})</span></span>
                </label>
              ))}
              {!report.loading && causes.length === 0 && <p className="hint">This report proposed no cause; choose "Rejected" or "Without an AI report".</p>}
              {causeIndex !== null && causes[causeIndex] && (
                <button type="button" className="btn-ghost small" onClick={() => setRootCause(causes[causeIndex].cause)}>
                  Copy AI cause text into the confirmed root cause (then verify and edit)
                </button>
              )}
            </fieldset>
          )}
        </div>
      )}

      <div className="grid-2">
        <Select id="res-cat" label="Root-cause category" value={category} options={opts.root_cause_category} onChange={setCategory} />
        <Select id="res-err" label="Which record was in error?" value={recordInError} options={opts.record_in_error} onChange={setRecordInError} />
        <Select id="res-out" label="Outcome" value={outcome} options={opts.outcome} onChange={setOutcome} />
      </div>

      <div className="field">
        <label htmlFor="res-cause">Confirmed root cause (your own finding)</label>
        <textarea id="res-cause" rows={3} value={rootCause} onChange={(e) => setRootCause(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="res-action">Final action taken</label>
        <textarea id="res-action" rows={2} value={finalAction} onChange={(e) => setFinalAction(e.target.value)}
                  placeholder="e.g. Servicing corrected the product in Loan IQ under ticket …" />
      </div>

      <fieldset className="field">
        <legend>Evidence supporting your conclusion</legend>
        {!pkg && <Loading what="Loading evidence" />}
        {pkg?.items.map((item) => (
          <label key={item.evidence_id} className="checkbox">
            <input type="checkbox" checked={evidence.includes(item.evidence_id)}
                   onChange={(e) => setEvidence(e.target.checked ? [...evidence, item.evidence_id] : evidence.filter((x) => x !== item.evidence_id))} />
            <span className="mono">{item.evidence_id}</span> {humanize(item.evidence_type)}
            <span className="muted small"> {item.source_reference.split(":").slice(-1)[0]}</span>
          </label>
        ))}
      </fieldset>

      <div className="field">
        <label htmlFor="res-notes">Notes <span className="muted">(optional)</span></label>
        <textarea id="res-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>

      {actorProblem && <p className="hint">{actorProblem}</p>}
      {!actorProblem && missing.length > 0 && <p className="hint">Still needed: {missing.join(", ")}.</p>}
      <ErrorBox error={error} title="Resolution not recorded" />
      <div className="button-row">
        <button type="button" disabled={busy || Boolean(actorProblem) || missing.length > 0} onClick={() => void submit()}>
          {busy ? "Recording…" : "Record resolution"}
        </button>
      </div>
    </Card>
  );
}

// --- View: what the AI suggested vs what the analyst confirmed ----------------------

function ResolutionView({ exceptionId, onOpenEvidence }: { exceptionId: string; onOpenEvidence: (id: string) => void }) {
  const res = useLoad(() => api.resolution(exceptionId), [exceptionId]);
  if (res.loading) return <Card title="Resolution"><Loading /></Card>;
  if (!res.data) return <Card title="Resolution"><ErrorBox error={res.error} /></Card>;
  const r: Resolution = res.data;
  const ai = r.ai_recommendation;

  return (
    <div className="grid-2 resolution-compare">
      <Card title="What the AI recommended" provenance="ai" className="ai-card">
        {!ai ? <Empty>Resolved without an AI report.</Empty> : (
          <>
            <p className="small muted">{ai.investigation_id} · {formatDateTime(ai.generated_at)}</p>
            <p>{ai.root_cause_statement}</p>
            <ol className="causes">
              {ai.probable_causes.map((c, i) => (
                <li key={i} className={`cause ${r.ai_cause_index === i ? "chosen" : ""}`}>
                  {c.cause} <span className="muted small">({humanize(c.claim_type)}, {c.confidence})</span>
                  {r.ai_cause_index === i && <span className="badge chosen-badge">Selected by analyst</span>}
                </li>
              ))}
            </ol>
            {ai.overall_assessment && <p className="small">{ai.overall_assessment}</p>}
          </>
        )}
      </Card>

      <Card title="What the analyst confirmed" provenance="analyst">
        <dl className="facts">
          <dt>Resolution</dt><dd className="mono">{r.resolution_id}</dd>
          <dt>Decision</dt><dd>{humanize(r.analyst_decision)}</dd>
          <dt>Root-cause category</dt><dd>{humanize(r.root_cause_category)}</dd>
          <dt>Confirmed root cause</dt><dd>{r.confirmed_root_cause}</dd>
          <dt>Record in error</dt><dd>{humanize(r.record_in_error)}</dd>
          <dt>Outcome</dt><dd>{humanize(r.outcome)}</dd>
          <dt>Final action</dt><dd>{r.final_action}</dd>
          <dt>Evidence</dt><dd><EvidenceChips ids={r.evidence_ids} typesById={{}} onOpen={onOpenEvidence} /></dd>
          {r.notes && (<><dt>Notes</dt><dd>{r.notes}</dd></>)}
          <dt>Resolved by</dt><dd>{r.resolved_by} · {formatDateTime(r.resolved_at)}</dd>
          <dt>Fed to history as</dt><dd className="mono">{r.historical_case_id ?? "—"}</dd>
        </dl>
      </Card>
    </div>
  );
}
