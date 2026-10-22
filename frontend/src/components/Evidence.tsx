import { useEffect } from "react";
import { api } from "../api/client";
import type { EvidencePackage, PackagedEvidence } from "../api/types";
import { display, formatDateTime, humanize } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { Card, Empty, ErrorBox, Loading } from "./common";

/** The evidence package for an exception: what the investigation is allowed to see. */
export function EvidenceList({
  pkg, onOpen,
}: {
  pkg: EvidencePackage;
  onOpen: (id: string) => void;
}) {
  return (
    <Card title={`Evidence package (${pkg.items.length} items)`} provenance="deterministic">
      <p className="muted small">
        Retrieved by the platform with deterministic rules. The AI investigation sees exactly these items and nothing else.
      </p>
      {pkg.gaps.length > 0 && (
        <div className="gaps">
          <strong>Gaps identified by the platform</strong>
          <ul>{pkg.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </div>
      )}
      <ul className="evidence-list">
        {pkg.items.map((item) => (
          <li key={item.evidence_id} className={`evidence-item type-${item.evidence_type.toLowerCase().replace(/_/g, "-")}`}>
            <div className="evidence-head">
              <button type="button" className="chip chip-neutral" onClick={() => onOpen(item.evidence_id)}>
                {item.evidence_id}
              </button>
              <span className="evidence-type">{humanize(item.evidence_type)}</span>
              <span className="muted small mono">{item.source_reference}</span>
            </div>
            <p className="evidence-why">{item.relevance}</p>
            <EvidenceGist item={item} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** One-line gist of an evidence item's content. */
function EvidenceGist({ item }: { item: PackagedEvidence }) {
  const c = item.content;
  let text: string;
  switch (item.evidence_type) {
    case "MAPPING_RULE":
      text = `${display(c.mapping_version)}: '${display(c.source_value)}' → '${display(c.target_value)}' (${display(c.status)}, ${display(c.effective_from)} to ${display(c.effective_to) === "—" ? "open" : display(c.effective_to)})`;
      break;
    case "AGREEMENT_CLAUSE":
      text = `${display(c.document_ref)} §${display(c.clause_number)} ${display(c.title)}: ${display(c.text)}`;
      break;
    case "HISTORICAL_CASE":
      text = `${display(c.case_id)} (${display(c.loan_id)}, ${display(c.outcome)}): ${display(c.confirmed_root_cause)}`;
      break;
    case "VALIDATION_FINDING":
      text = `${display(c.exception_id)} ${display(c.rule_id)}: ${display(c.explanation)}`;
      break;
    default:
      text = `${display(c.product_code_as_received)} · ${display(c.currency)} ${display(c.amount)} · matures ${display(c.maturity_date)} · ${display(c.status)}`;
  }
  return <p className="evidence-gist">{text}</p>;
}

/** Side drawer: the full evidence snapshot plus a live traceability check. */
export function EvidenceDrawer({
  evidenceId, packaged, onClose,
}: {
  evidenceId: string | null;
  packaged: PackagedEvidence | undefined;
  onClose: () => void;
}) {
  const trace = useLoad(() => (evidenceId ? api.evidence(evidenceId) : Promise.resolve(undefined)), [evidenceId]);

  useEffect(() => {
    if (!evidenceId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [evidenceId, onClose]);

  if (!evidenceId) return null;
  const item = trace.data?.evidence;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label={`Evidence ${evidenceId}`} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <h2>{evidenceId}</h2>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </header>
        {trace.loading && <Loading what="Loading evidence" />}
        <ErrorBox error={trace.error} />
        {!trace.loading && !trace.error && !item && <Empty>Evidence not found.</Empty>}
        {item && trace.data && (
          <>
            <p>
              <span className="evidence-type">{humanize(item.evidence_type)}</span>{" "}
              <span className={`trace trace-${trace.data.traceability_status.toLowerCase().replace(/_/g, "-")}`}>
                {humanize(trace.data.traceability_status)}
              </span>
            </p>
            <p className="muted small">{trace.data.traceability_detail}</p>
            <dl className="facts">
              <dt>Source</dt><dd className="mono">{item.source_reference}</dd>
              <dt>Version</dt><dd>{item.source_version ?? "—"}</dd>
              <dt>Captured</dt><dd>{formatDateTime(item.created_at)}</dd>
              {packaged && (<><dt>Why retrieved</dt><dd>{packaged.relevance}</dd></>)}
            </dl>
            <h3>Content (snapshot)</h3>
            <dl className="facts content">
              {Object.entries(item.content).map(([key, value]) => (
                <div className="fact-row" key={key}>
                  <dt>{humanize(key)}</dt>
                  <dd>{typeof value === "object" && value !== null ? <pre>{display(value)}</pre> : display(value)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </aside>
    </div>
  );
}
