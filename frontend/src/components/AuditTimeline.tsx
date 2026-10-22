import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { AuditEvent } from "../api/types";
import { humanize } from "../lib/format";
import { useLoad } from "../lib/hooks";
import { ActorBadge, Card, Empty, ErrorBox, Icon, type IconName, Loading, StatusBadge } from "./common";

type Filter = "ALL" | "ANALYST" | "SYSTEM" | "AI";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "ALL", label: "All events" },
  { key: "ANALYST", label: "Analyst decisions" },
  { key: "SYSTEM", label: "Platform" },
  { key: "AI", label: "AI" },
];

const matches = (e: AuditEvent, f: Filter) =>
  f === "ALL" || (f === "AI" ? e.actor_type === "AI" || e.actor_type === "AI_SERVICE" : e.actor_type === f);

const EVENT_META: Record<string, { title: string; icon: IconName }> = {
  EXCEPTION_CREATED: { title: "Exception detected", icon: "search" },
  STATUS_CHANGED: { title: "Status changed", icon: "steps" },
  EVIDENCE_RETRIEVED: { title: "Evidence gathered", icon: "doc" },
  AI_INVESTIGATION_REQUESTED: { title: "AI investigation requested", icon: "spark" },
  AI_INVESTIGATION_SUCCEEDED: { title: "AI report produced", icon: "spark" },
  AI_INVESTIGATION_FAILED: { title: "AI investigation failed", icon: "x" },
  RESOLUTION_RECORDED: { title: "Resolution recorded", icon: "check" },
};

const ACTOR_ICON: Record<string, IconName> = { ANALYST: "user", SYSTEM: "gear", AI: "spark", AI_SERVICE: "gear" };

function asUtc(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}
const dayLabel = (d: Date) => d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
const timeLabel = (d: Date) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** UPPER_SNAKE vocabulary in summaries -> readable words; IDs such as RULE-MAP-001 are left alone. */
function humanizeTokens(text: string): string {
  return text.replace(/(?<![\w-])[A-Z][A-Z_]{3,}(?![\w-])/g, (token) => humanize(token).toLowerCase().replace(/\bai\b/g, "AI"))
    .replace(/^./, (c) => c.toUpperCase());
}

/** Summary with status transitions drawn as badges. */
function Summary({ event }: { event: AuditEvent }) {
  let text = event.summary;
  // The audit record keeps the model name; the workbench does not display it.
  if (event.event_type === "AI_INVESTIGATION_REQUESTED") text = text.replace(/\s*\([^)]*\)\.?$/, ".");

  const transition = text.match(/^Status ([A-Z_]+) → ([A-Z_]+)\.?\s*(.*)$/);
  if (transition) {
    return (
      <div className="ev-summary">
        <span className="transition"><StatusBadge status={transition[1]} /> <span className="arrow">→</span> <StatusBadge status={transition[2]} /></span>
        {transition[3] && <p>{humanizeTokens(transition[3])}</p>}
      </div>
    );
  }
  const created = text.match(/^Exception created \(([A-Z_]+)\)\.?\s*(.*)$/);
  if (created) {
    return (
      <div className="ev-summary">
        <span className="transition">Opened as <StatusBadge status={created[1]} /></span>
        {created[2] && <p>{humanizeTokens(created[2])}</p>}
      </div>
    );
  }
  return <div className="ev-summary"><p>{humanizeTokens(text)}</p></div>;
}

export function AuditTimeline({ exceptionId, version }: { exceptionId: string; version: number }) {
  const audit = useLoad(() => api.audit(exceptionId), [exceptionId, version]);
  const [filter, setFilter] = useState<Filter>("ALL");
  const events = audit.data ?? [];

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { ALL: 0, ANALYST: 0, SYSTEM: 0, AI: 0 };
    for (const e of events) for (const f of FILTERS) if (matches(e, f.key)) c[f.key] += 1;
    return c;
  }, [events]);

  // Newest first reads like an activity feed; grouped by calendar day.
  const groups = useMemo(() => {
    const out: { day: string; items: { e: AuditEvent; d: Date }[] }[] = [];
    for (const e of [...events].reverse()) {
      if (!matches(e, filter)) continue;
      const d = asUtc(e.at);
      const day = dayLabel(d);
      const last = out[out.length - 1];
      if (last && last.day === day) last.items.push({ e, d });
      else out.push({ day, items: [{ e, d }] });
    }
    return out;
  }, [events, filter]);

  return (
    <Card title={<>Audit trail <span className="rsec-count">{events.length}</span></>}
          actions={<span className="small muted">Newest first</span>}>
      {audit.loading && !audit.data && <Loading />}
      <ErrorBox error={audit.error} />
      {audit.data && events.length === 0 && <Empty>No events.</Empty>}
      {events.length > 0 && (
        <>
          <div className="audit-filters" role="toolbar" aria-label="Filter events by actor">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" aria-pressed={filter === f.key}
                      className={`filter-chip filter-${f.key.toLowerCase()} ${filter === f.key ? "active" : ""}`}
                      onClick={() => setFilter(f.key)} disabled={f.key !== "ALL" && counts[f.key] === 0}>
                {f.label} <span className="filter-count">{counts[f.key]}</span>
              </button>
            ))}
          </div>

          {groups.length === 0 && <Empty>No events for this filter.</Empty>}
          {groups.map((g) => (
            <div key={g.day} className="audit-day">
              <p className="audit-day-label">{g.day}</p>
              <ol className="tl">
                {g.items.map(({ e, d }, i) => {
                  const meta = EVENT_META[e.event_type] ?? { title: humanize(e.event_type), icon: "info" as IconName };
                  const tone = e.actor_type.toLowerCase().replace(/_/g, "-");
                  return (
                    <li key={`${e.at}-${i}`} className={`tl-item tl-${tone} ${e.event_type === "AI_INVESTIGATION_FAILED" ? "tl-failed" : ""}`}>
                      <time className="tl-time" dateTime={e.at}>{timeLabel(d)}</time>
                      <span className="tl-node"><Icon name={meta.icon} size={13} /></span>
                      <div className="tl-card">
                        <div className="tl-head">
                          <strong className="tl-title">{meta.title}</strong>
                          {e.reference && <code className="tl-ref">{e.reference}</code>}
                        </div>
                        <Summary event={e} />
                        <Actor event={e} />
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </>
      )}
    </Card>
  );
}

function Actor({ event }: { event: AuditEvent }) {
  // AI events: the actor string is the model name, which the workbench does not show.
  const name = event.actor_type === "AI" ? null : event.actor.replace(/^system:/, "");
  return (
    <p className="tl-actor">
      <Icon name={ACTOR_ICON[event.actor_type] ?? "info"} size={12} />
      <ActorBadge actorType={event.actor_type} />
      {name && <span className="mono">{name}</span>}
    </p>
  );
}
