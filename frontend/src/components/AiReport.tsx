import type { ReactNode } from "react";
import type { AiReport } from "../api/types";
import { humanize } from "../lib/format";
import { EvidenceChips, Icon, type IconName } from "./common";

/**
 * Renders an AI investigation report. Every claim is shown next to the
 * evidence it cites; clicking an ID opens that evidence, so the analyst can
 * check each claim instead of trusting the summary.
 *
 * Reading order: verdict -> the discrepancy -> probable causes -> what the
 * evidence shows -> next steps -> gaps and open questions.
 */
export function AiReportView({
  report, typesById, onOpenEvidence,
}: {
  report: AiReport;
  typesById: Record<string, string>;
  onOpenEvidence: (id: string) => void;
}) {
  const chips = (ids: string[], tone: "neutral" | "support" | "contradict" = "neutral") => (
    <EvidenceChips ids={ids} typesById={typesById} onOpen={onOpenEvidence} tone={tone} />
  );
  const insufficient = report.evidence_sufficiency === "INSUFFICIENT";
  const escalate = report.escalation.recommended;

  const openQuestions =
    report.missing_information.length + report.uncertainties.length +
    report.conflicting_evidence.length + report.alternative_explanations.length;

  return (
    <div className="ai-report">
      {/* Verdict ------------------------------------------------------------ */}
      <section className={`verdict ${insufficient ? "verdict-insufficient" : ""}`}>
        <div className="verdict-pills">
          <span className={`pill ${insufficient ? "pill-warn" : "pill-ok"}`}>
            <Icon name={insufficient ? "alert" : "check"} />
            {insufficient ? "Insufficient evidence" : "Sufficient for a hypothesis"}
          </span>
          <span className={`pill ${escalate ? "pill-danger" : "pill-neutral"}`}>
            <Icon name="flag" />
            {escalate ? "Escalation recommended" : "No escalation needed"}
          </span>
        </div>
        <p className="verdict-label">Overall assessment</p>
        <p className="verdict-text">{report.overall_assessment}</p>
        <p className="verdict-caveat">{report.root_cause_statement}</p>
        {report.escalation.reason && (
          <p className="verdict-escalation"><strong>Escalation:</strong> {report.escalation.reason}</p>
        )}
        <dl className="verdict-stats">
          <div><dt>Probable causes</dt><dd>{report.probable_causes.length}</dd></div>
          <div><dt>Evidence-backed facts</dt><dd>{report.confirmed_facts.length}</dd></div>
          <div><dt>Next steps</dt><dd>{report.recommended_checks.length}</dd></div>
          <div><dt>Open questions</dt><dd>{openQuestions}</dd></div>
        </dl>
      </section>

      {report.policy_flags.length > 0 && (
        <div className="policy-flags" role="alert">
          <strong><Icon name="alert" /> Policy flags</strong>
          <ul>{report.policy_flags.map((f) => <li key={f}>{f}</li>)}</ul>
        </div>
      )}

      {/* The discrepancy (deterministic) ------------------------------------ */}
      <Section icon="compare" title="The discrepancy" tag={<span className="prov prov-deterministic">Deterministic validation</span>}>
        {report.observed_discrepancies.map((d) => (
          <div key={d.validation_rule_id} className="disc">
            <div className="disc-head">
              <span className="disc-field">{humanize(d.field)}</span>
              <code>{d.validation_rule_id}</code>
            </div>
            <div className="disc-values">
              <div className="disc-side">
                <span className="disc-label">Upstream · origination</span>
                <span className="disc-value">{d.upstream_value ?? "—"}</span>
              </div>
              <span className="disc-vs" aria-hidden>≠</span>
              <div className="disc-side">
                <span className="disc-label">Downstream · servicing</span>
                <span className="disc-value">{d.downstream_value ?? "—"}</span>
              </div>
            </div>
          </div>
        ))}
        <p className="ai-summary"><span className="ai-summary-label">Model summary</span>{report.summary}</p>
      </Section>

      {/* Probable causes ---------------------------------------------------- */}
      <Section icon="bulb" title="Probable causes" count={report.probable_causes.length} hint="Hypotheses for you to verify — not confirmed">
        {report.probable_causes.length === 0 ? <p className="muted">No cause proposed.</p> : (
          <ol className="cause-list">
            {report.probable_causes.map((c, i) => {
              const supported = c.claim_type === "EVIDENCE_SUPPORTED_HYPOTHESIS";
              return (
                <li key={i} className={`cause-card ${supported ? "cause-supported" : "cause-unverified"}`}>
                  <span className="cause-rank">{i + 1}</span>
                  <div className="cause-main">
                    <p className="cause-title">{c.cause}</p>
                    <div className="cause-tags">
                      <span className={`badge ${supported ? "claim-supported" : "claim-unverified"}`}>
                        {supported ? "Backed by evidence" : "Unverified possibility"}
                      </span>
                      <ConfidenceMeter level={c.confidence} note={report.confidence_note} />
                    </div>
                    <p className="cause-reasoning">{c.reasoning}</p>
                    <div className="cause-evidence">
                      <span className="ev-label ev-label-support">Supports</span>
                      {chips(c.supporting_evidence_ids, "support")}
                    </div>
                    {c.contradicting_evidence_ids.length > 0 && (
                      <div className="cause-evidence">
                        <span className="ev-label ev-label-contradict">Contradicts</span>
                        {chips(c.contradicting_evidence_ids, "contradict")}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Section>

      {/* Facts --------------------------------------------------------------- */}
      <Section icon="check" title="What the evidence shows" count={report.confirmed_facts.length}>
        {report.confirmed_facts.length === 0 ? <p className="muted">No facts stated.</p> : (
          <ul className="fact-list">
            {report.confirmed_facts.map((f, i) => (
              <li key={i}>
                <span className="fact-tick" aria-hidden><Icon name="check" /></span>
                <span className="fact-text">{f.statement}</span>
                <span className="fact-ev">{chips(f.evidence_ids)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Next steps ---------------------------------------------------------- */}
      <Section icon="steps" title="Recommended next steps" count={report.recommended_checks.length}>
        <ol className="step-list">
          {report.recommended_checks.map((c, i) => (
            <li key={i}>
              <span className="step-num">{i + 1}</span>
              <div>
                <p className="step-title">{c.step}</p>
                <p className="step-purpose">{c.purpose}</p>
                <div className="step-basis">
                  {c.basis === "MISSING_INFORMATION"
                    ? <span className="badge basis-gap">Fills missing information</span>
                    : <><span className="ev-label">Based on</span>{chips(c.evidence_ids)}</>}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      {/* Gaps and open questions -------------------------------------------- */}
      {openQuestions > 0 && (
        <Section icon="question" title="Gaps and open questions" count={openQuestions}>
          <div className="gap-grid">
            {report.missing_information.length > 0 && (
              <GapCard tone="warn" title="Missing information">
                {report.missing_information.map((m, i) => (
                  <li key={i}><strong>{m.item}</strong><span className="muted"> — {m.why_needed}</span></li>
                ))}
              </GapCard>
            )}
            {report.conflicting_evidence.length > 0 && (
              <GapCard tone="danger" title="Conflicting evidence">
                {report.conflicting_evidence.map((c, i) => <li key={i}>{c.description} {chips(c.evidence_ids)}</li>)}
              </GapCard>
            )}
            {report.alternative_explanations.length > 0 && (
              <GapCard tone="neutral" title="Alternative explanations">
                {report.alternative_explanations.map((a, i) => (
                  <li key={i}>
                    {a.explanation}
                    <span className="muted"> — less likely: {a.why_less_likely}</span>{" "}
                    {a.supporting_evidence_ids.length > 0 && chips(a.supporting_evidence_ids)}
                  </li>
                ))}
              </GapCard>
            )}
            {report.uncertainties.length > 0 && (
              <GapCard tone="neutral" title="Uncertainties">
                {report.uncertainties.map((u, i) => <li key={i}>{u}</li>)}
              </GapCard>
            )}
          </div>
        </Section>
      )}

      <p className="confidence-note"><Icon name="info" /> {report.confidence_note}</p>
    </div>
  );
}

function Section({
  icon, title, count, hint, tag, children,
}: {
  icon: IconName;
  title: string;
  count?: number;
  hint?: string;
  tag?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rsec">
      <header className="rsec-head">
        <span className="rsec-icon"><Icon name={icon} /></span>
        <h3>{title}</h3>
        {count !== undefined && <span className="rsec-count">{count}</span>}
        {tag}
        {hint && <span className="rsec-hint">{hint}</span>}
      </header>
      {children}
    </section>
  );
}

function GapCard({ tone, title, children }: { tone: "warn" | "danger" | "neutral"; title: string; children: ReactNode }) {
  return (
    <div className={`gap-card gap-${tone}`}>
      <p className="gap-title">{title}</p>
      <ul>{children}</ul>
    </div>
  );
}

const LEVEL: Record<string, number> = { low: 1, medium: 2, high: 3 };

/** Qualitative only: three segments for low / medium / high. Never a percentage. */
export function ConfidenceMeter({ level, note }: { level: string; note?: string }) {
  const filled = LEVEL[level] ?? 0;
  return (
    <span className={`conf-meter conf-${level}`} title={note}>
      <span className="conf-bars" aria-hidden>
        {[1, 2, 3].map((n) => <span key={n} className={n <= filled ? "on" : ""} />)}
      </span>
      {humanize(level)} confidence
    </span>
  );
}
