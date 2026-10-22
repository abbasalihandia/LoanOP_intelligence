import { useEffect, useState } from "react";
import { api } from "../api/client";
import { AuditTimeline } from "../components/AuditTimeline";
import { Card, ErrorBox, Loading, SeverityBadge, StatusBadge } from "../components/common";
import { EvidenceDrawer, EvidenceList } from "../components/Evidence";
import { InvestigationPanel } from "../components/InvestigationPanel";
import { RecordComparison } from "../components/RecordComparison";
import { ResolutionPanel } from "../components/Resolution";
import { StatusControls } from "../components/StatusControls";
import { formatDateTime, humanize } from "../lib/format";
import { type DetailTab, detailHref, useLoad } from "../lib/hooks";

const TABS: { id: DetailTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "evidence", label: "Evidence" },
  { id: "ai", label: "AI investigation" },
  { id: "resolution", label: "Resolution" },
  { id: "audit", label: "Audit trail" },
];

export function ExceptionDetailPage({ exceptionId, tab }: { exceptionId: string; tab: DetailTab }) {
  const [version, setVersion] = useState(0);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const refresh = () => setVersion((v) => v + 1);

  // Switching tabs closes the evidence drawer, so it never hides the new tab.
  useEffect(() => setOpenEvidence(null), [tab]);

  const detail = useLoad(() => api.exception(exceptionId), [exceptionId, version]);
  const pkg = useLoad(() => api.evidencePackage(exceptionId), [exceptionId, version]);

  if (detail.loading && !detail.data) return <Loading what={`Loading ${exceptionId}`} />;
  if (!detail.data) {
    return (
      <div className="stack">
        <a href="#/">← All exceptions</a>
        <ErrorBox error={detail.error} />
      </div>
    );
  }
  const e = detail.data;

  return (
    <div className="stack">
      <a href="#/" className="back">← All exceptions</a>

      <div className="page-head">
        <div>
          <h1>
            <span className="mono">{e.exception_id}</span> · {humanize(e.category)}
          </h1>
          <p className="lede">
            Loan <strong className="mono">{e.loan_id}</strong> · rule <code>{e.rule_id}</code> · detected{" "}
            {e.detection_count}× · last {formatDateTime(e.last_detected_at)}
          </p>
        </div>
        <div className="head-badges">
          <SeverityBadge severity={e.severity} />
          <StatusBadge status={e.status} />
        </div>
      </div>
      {!e.still_detected && (
        <p className="notice">
          This discrepancy was not found in the latest validation run. It stays open until an analyst closes it.
        </p>
      )}

      <nav className="tabs" aria-label="Exception sections">
        {TABS.map((t) => (
          <a key={t.id} href={detailHref(e.exception_id, t.id)} className={t.id === tab ? "tab active" : "tab"}
             aria-current={t.id === tab ? "page" : undefined}>
            {t.label}
          </a>
        ))}
      </nav>

      {tab === "overview" && (
        <>
          <Card title="Discrepancy" provenance="deterministic">
            <p className="explanation">{e.explanation}</p>
            <RecordComparison upstream={e.upstream_record} downstream={e.downstream_record} focusField={e.field_name} />
          </Card>
          <Card title="Status">
            <p>Current status: <StatusBadge status={e.status} /></p>
            <StatusControls exception={e} onChanged={refresh} />
            <details className="small">
              <summary>Status history ({e.status_history.length})</summary>
              <ul className="plain">
                {e.status_history.map((h, i) => (
                  <li key={i}>
                    {formatDateTime(h.changed_at)} · {h.from_status ? `${humanize(h.from_status)} → ` : ""}
                    {humanize(h.to_status)} · <span className="mono">{h.actor}</span>
                    {h.reason && <span className="muted"> — {h.reason}</span>}
                  </li>
                ))}
              </ul>
            </details>
          </Card>
        </>
      )}

      {tab === "evidence" && (
        <>
          {pkg.loading && !pkg.data && <Loading what="Retrieving evidence" />}
          <ErrorBox error={pkg.error} />
          {pkg.data && <EvidenceList pkg={pkg.data} onOpen={setOpenEvidence} />}
        </>
      )}

      {tab === "ai" && <InvestigationPanel exception={e} onChanged={refresh} onOpenEvidence={setOpenEvidence} />}

      {tab === "resolution" && (
        <ResolutionPanel exception={e} pkg={pkg.data} onChanged={refresh} onOpenEvidence={setOpenEvidence} />
      )}

      {tab === "audit" && <AuditTimeline exceptionId={e.exception_id} version={version} />}

      <EvidenceDrawer
        evidenceId={openEvidence}
        packaged={pkg.data?.items.find((i) => i.evidence_id === openEvidence)}
        onClose={() => setOpenEvidence(null)}
      />
    </div>
  );
}
