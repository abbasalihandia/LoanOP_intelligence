import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { humanize } from "../lib/format";

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge sev-${severity.toLowerCase()}`}>{severity}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge st-${status.toLowerCase().replace(/_/g, "-")}`}>{humanize(status)}</span>;
}

const ACTOR_LABEL: Record<string, string> = {
  ANALYST: "Analyst",
  SYSTEM: "Platform",
  AI: "AI model",
  AI_SERVICE: "AI service",
};

export function ActorBadge({ actorType }: { actorType: string }) {
  return <span className={`badge actor-${actorType.toLowerCase().replace(/_/g, "-")}`}>{ACTOR_LABEL[actorType] ?? actorType}</span>;
}

/** Where a piece of information comes from. Used everywhere to keep sources distinct. */
export type Provenance = "deterministic" | "ai" | "analyst";

const PROVENANCE_LABEL: Record<Provenance, string> = {
  deterministic: "Deterministic validation",
  ai: "AI-generated · not a confirmed finding",
  analyst: "Analyst-confirmed",
};

export function ProvenanceTag({ kind }: { kind: Provenance }) {
  return <span className={`prov prov-${kind}`}>{PROVENANCE_LABEL[kind]}</span>;
}

export function Card({
  title, provenance, actions, children, className = "",
}: {
  title?: ReactNode;
  provenance?: Provenance;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${provenance ? `card-${provenance}` : ""} ${className}`}>
      {(title || provenance || actions) && (
        <header className="card-head">
          <div className="card-title">
            {title && <h2>{title}</h2>}
            {provenance && <ProvenanceTag kind={provenance} />}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function ErrorBox({ error, title }: { error: ApiError | string | null | undefined; title?: string }) {
  if (!error) return null;
  const message = typeof error === "string" ? error : error.message;
  const code = typeof error === "string" ? undefined : error.code;
  const reference = typeof error === "string" ? undefined : error.reference;
  return (
    <div className="error-box" role="alert">
      {title && <p className="error-title">{title}</p>}
      <p className="error-msg">
        {code && <code className="error-code">{code}</code>} {message}
      </p>
      {reference && <p className="muted">Audit reference: {reference}</p>}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted loading">{what}…</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

const TYPE_SHORT: Record<string, string> = {
  VALIDATION_FINDING: "Finding",
  UPSTREAM_RECORD: "Upstream",
  DOWNSTREAM_RECORD: "Downstream",
  MAPPING_RULE: "Mapping",
  AGREEMENT_CLAUSE: "Clause",
  HISTORICAL_CASE: "Past case",
};

/** Clickable evidence ID chips. Clicking opens the evidence drawer. */
export function EvidenceChips({
  ids, typesById, onOpen, tone = "neutral",
}: {
  ids: string[];
  typesById: Record<string, string>;
  onOpen: (id: string) => void;
  tone?: "neutral" | "support" | "contradict";
}) {
  if (ids.length === 0) return <span className="muted small">no evidence cited</span>;
  return (
    <span className="chips">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className={`chip chip-${tone} type-${(typesById[id] ?? "unknown").toLowerCase().replace(/_/g, "-")}`}
          title={typesById[id] ? humanize(typesById[id]) : "Not in this package"}
          onClick={() => onOpen(id)}
        >
          {TYPE_SHORT[typesById[id]] && <span className="chip-type">{TYPE_SHORT[typesById[id]]}</span>}
          {id}
        </button>
      ))}
    </span>
  );
}

/* Small stroke icons (24x24 grid). Decorative only. */
const ICON_PATHS = {
  check: "M5 12.5l4.5 4.5L19 7.5",
  alert: "M12 4l9 16H3L12 4zM12 10v4.5M12 17.5v.5",
  flag: "M6 21V4M6 4h11l-2 4 2 4H6",
  compare: "M4 7h12M13 4l3 3-3 3M20 17H8M11 14l-3 3 3 3",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z",
  steps: "M4 6h2M4 12h2M4 18h2M9 6h11M9 12h11M9 18h11",
  question: "M9.2 9a3 3 0 1 1 4.2 2.8c-.8.4-1.4 1.1-1.4 2v.7M12 17.5v.5",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 21a7.5 7.5 0 0 1 15 0",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1",
  spark: "M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9L12 3zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16z",
  doc: "M7 3h7l5 5v13H7V3zM14 3v5h5M10 13h6M10 17h6",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  x: "M6 6l12 12M18 6L6 18",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
} as const;

export type IconName = keyof typeof ICON_PATHS;

export function Icon({ name, size = 14 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}
