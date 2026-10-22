// Response types mirroring backend/app/schemas.py. Amounts are decimal strings;
// timestamps are UTC ISO strings (naive strings from the backend are UTC).

export type Json = Record<string, unknown>;

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  data_mode: "synthetic";
  server_time_utc: string;
}

export interface LoanRecord {
  loan_id: string;
  source_system: string;
  version: number;
  is_current: boolean;
  facility_id: string | null;
  borrower_name: string | null;
  product_type: string | null;
  product_code_raw: string | null;
  currency: string | null;
  amount: string | null;
  maturity_date: string | null;
  status: string | null;
  mapping_version: string | null;
  booking_error: string | null;
  source_updated_at: string | null;
  ingested_at: string;
  normalization_issues: Json[];
  raw_record_id: number;
}

export interface ExceptionSummary {
  exception_id: string;
  loan_id: string;
  rule_id: string;
  category: string;
  severity: string;
  status: string;
  side: string;
  field_name: string | null;
  source_value: string | null;
  target_value: string | null;
  explanation: string;
  still_detected: boolean;
  detection_count: number;
  first_detected_at: string;
  last_detected_at: string;
  updated_at: string;
}

export interface StatusChange {
  from_status: string | null;
  to_status: string;
  actor: string;
  reason: string | null;
  changed_at: string;
}

export interface ExceptionDetail extends ExceptionSummary {
  details: Json;
  first_run_id: string;
  last_run_id: string;
  created_at: string;
  upstream_record: LoanRecord | null;
  downstream_record: LoanRecord | null;
  status_history: StatusChange[];
  allowed_next_statuses: string[];
  can_resolve: boolean;
}

export interface ExceptionCounts {
  total: number;
  active: number;
  active_no_longer_detected: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
}

export interface ValidationRun {
  run_id: string;
  loans_evaluated: number;
  findings: number;
  created: number;
  redetected: number;
  suppressed: number;
  no_longer_detected: number;
}

// --- Evidence ---------------------------------------------------------------

export interface PackagedEvidence {
  evidence_id: string;
  evidence_type: string;
  source_reference: string;
  source_version: string | null;
  loan_id: string | null;
  retrieval_method: string;
  relevance: string;
  score: number | null;
  content: Json;
}

export interface EvidencePackage {
  exception_id: string;
  loan_id: string;
  items: PackagedEvidence[];
  gaps: string[];
}

export interface EvidenceTrace {
  evidence: {
    evidence_id: string;
    evidence_type: string;
    source_reference: string;
    source_version: string | null;
    loan_id: string | null;
    content: Json;
    content_hash: string;
    created_at: string;
  };
  traceability_status: "CURRENT" | "SOURCE_CHANGED" | "SOURCE_MISSING";
  traceability_detail: string;
}

// --- AI ------------------------------------------------------------------------

export interface AiStatus {
  ollama_base_url: string;
  model: string;
  reachable: boolean;
  model_available: boolean;
  available_models: string[];
  error_code: string | null;
  error: string | null;
}

export interface ConfirmedFact {
  statement: string;
  evidence_ids: string[];
}

export interface ProbableCause {
  cause: string;
  claim_type: "EVIDENCE_SUPPORTED_HYPOTHESIS" | "UNVERIFIED_POSSIBILITY";
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  reasoning: string;
  confidence: "low" | "medium" | "high";
}

export interface AiReport {
  report_type: string;
  disclaimer: string;
  exception_id: string;
  summary: string;
  observed_discrepancies: {
    field: string | null;
    upstream_value: string | null;
    downstream_value: string | null;
    validation_rule_id: string;
    explanation: string;
    source: string;
  }[];
  evidence_sufficiency: "SUFFICIENT_FOR_HYPOTHESIS" | "INSUFFICIENT";
  root_cause_statement: string;
  confirmed_facts: ConfirmedFact[];
  probable_causes: ProbableCause[];
  alternative_explanations: { explanation: string; supporting_evidence_ids: string[]; why_less_likely: string }[];
  conflicting_evidence: { description: string; evidence_ids: string[] }[];
  recommended_checks: { step: string; purpose: string; basis: string; evidence_ids: string[] }[];
  missing_information: { item: string; why_needed: string }[];
  uncertainties: string[];
  escalation: { recommended: boolean; reason: string };
  overall_assessment: string;
  confidence_note: string;
  policy_flags: string[];
  evidence_package_ids: string[];
  model: string;
  generated_at: string;
}

export interface InvestigationSummary {
  investigation_id: string;
  exception_id: string;
  requested_by: string;
  model: string;
  status: "SUCCEEDED" | "FAILED";
  error_code: string | null;
  attempts: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

export interface InvestigationAudit extends InvestigationSummary {
  error_message: string | null;
  evidence_ids: string[];
  prompt_sha256: string;
  validation_errors: { attempt: number; errors: string[] }[];
  report: AiReport | null;
  evidence_package: { items?: PackagedEvidence[]; gaps?: string[] };
  raw_responses: string[];
}

// --- Resolution and audit --------------------------------------------------------

export interface Option {
  value: string;
  label: string;
}

export interface ResolutionOptions {
  analyst_decision: Option[];
  root_cause_category: Option[];
  record_in_error: Option[];
  outcome: Option[];
}

export interface Resolution {
  resolution_id: string;
  exception_id: string;
  loan_id: string;
  rule_id: string;
  category: string;
  ai_investigation_id: string | null;
  ai_recommendation: {
    investigation_id: string;
    model: string;
    generated_at: string | null;
    evidence_sufficiency: string | null;
    root_cause_statement: string | null;
    probable_causes: ProbableCause[];
    overall_assessment: string | null;
    label: string;
  } | null;
  ai_cause_index: number | null;
  analyst_decision: string;
  root_cause_category: string;
  confirmed_root_cause: string;
  record_in_error: string;
  final_action: string;
  outcome: string;
  evidence_ids: string[];
  notes: string | null;
  resolved_by: string;
  resolved_at: string;
  historical_case_id: string | null;
}

export interface ResolutionInput {
  resolved_by: string;
  analyst_decision: string;
  ai_investigation_id: string | null;
  ai_cause_index: number | null;
  root_cause_category: string;
  confirmed_root_cause: string;
  record_in_error: string;
  final_action: string;
  outcome: string;
  evidence_ids: string[];
  notes: string | null;
}

export interface AuditEvent {
  at: string;
  event_type: string;
  actor: string;
  actor_type: "ANALYST" | "SYSTEM" | "AI" | "AI_SERVICE";
  summary: string;
  reference: string | null;
}
