import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { ExceptionDetail } from "../api/types";
import { analystIdProblem, useAnalyst } from "../lib/analyst";
import { humanize } from "../lib/format";
import { ErrorBox } from "./common";

// Mirrors backend REASON_REQUIRED; the backend enforces it regardless.
const NEEDS_REASON = new Set(["REJECTED", "ESCALATED", "AWAITING_EVIDENCE"]);

export function StatusControls({ exception, onChanged }: { exception: ExceptionDetail; onChanged: () => void }) {
  const { analystId } = useAnalyst();
  const [target, setTarget] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const options = exception.allowed_next_statuses;
  const actorProblem = analystIdProblem(analystId);

  if (options.length === 0) {
    return <p className="muted small">No further status changes are possible ({humanize(exception.status)}).</p>;
  }

  async function submit() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await api.changeStatus(exception.exception_id, target, analystId.trim(), reason.trim() || null);
      setTarget(null);
      setReason("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(String(err)));
    } finally {
      setBusy(false);
    }
  }

  const reasonMissing = target !== null && NEEDS_REASON.has(target) && !reason.trim();

  return (
    <div className="status-controls">
      <div className="button-row">
        {options.map((s) => (
          <button key={s} type="button" className={target === s ? "btn-secondary active" : "btn-secondary"}
                  disabled={Boolean(actorProblem) || busy} onClick={() => setTarget(target === s ? null : s)}>
            {humanize(s)}
          </button>
        ))}
      </div>
      {actorProblem && <p className="hint">{actorProblem}</p>}
      {target && (
        <div className="status-form">
          <label htmlFor="status-reason">
            Reason {NEEDS_REASON.has(target) ? <span className="required">(required)</span> : <span className="muted">(optional)</span>}
          </label>
          <textarea id="status-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="button-row">
            <button type="button" disabled={busy || reasonMissing} onClick={() => void submit()}>
              {busy ? "Saving…" : `Move to ${humanize(target)}`}
            </button>
            <button type="button" className="btn-ghost" onClick={() => setTarget(null)}>Cancel</button>
          </div>
        </div>
      )}
      <ErrorBox error={error} />
    </div>
  );
}
