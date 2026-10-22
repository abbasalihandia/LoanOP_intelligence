import type { LoanRecord } from "../api/types";
import { formatAmount, formatDateTime } from "../lib/format";

interface Row {
  key: string;
  label: string;
  value: (r: LoanRecord) => string | null;
  compare?: (r: LoanRecord) => string | null;
  /** Legitimately empty (e.g. upstream has no mapping version): show "—", not "missing". */
  optional?: boolean;
}

const ROWS: Row[] = [
  { key: "facility_id", label: "Facility", value: (r) => r.facility_id },
  { key: "borrower_name", label: "Borrower", value: (r) => r.borrower_name, optional: true },
  {
    key: "product_type",
    label: "Product",
    value: (r) => (r.product_code_raw ? `${r.product_code_raw}${r.product_type ? ` [${r.product_type}]` : ""}` : null),
    compare: (r) => r.product_type,
  },
  { key: "currency", label: "Currency", value: (r) => r.currency },
  { key: "amount", label: "Amount", value: (r) => (r.amount === null ? null : formatAmount(r.amount)), compare: (r) => (r.amount === null ? null : String(Number(r.amount))) },
  { key: "maturity_date", label: "Maturity date", value: (r) => r.maturity_date },
  { key: "status", label: "Status", value: (r) => r.status },
  { key: "mapping_version", label: "Mapping version", value: (r) => r.mapping_version, optional: true },
  { key: "booking_error", label: "Booking error", value: (r) => r.booking_error, optional: true },
];

// Fields that are expected to differ between systems and are not discrepancies.
const NOT_COMPARED = new Set(["borrower_name", "status", "mapping_version", "booking_error"]);

export function RecordComparison({
  upstream, downstream, focusField,
}: {
  upstream: LoanRecord | null;
  downstream: LoanRecord | null;
  focusField: string | null;
}) {
  return (
    <div className="table-wrap">
      <table className="compare">
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Upstream {upstream ? <span className="muted">({upstream.source_system}, v{upstream.version})</span> : null}</th>
            <th scope="col">Downstream {downstream ? <span className="muted">({downstream.source_system}, v{downstream.version})</span> : null}</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => {
            const up = upstream ? row.value(upstream) : null;
            const down = downstream ? row.value(downstream) : null;
            const cmp = row.compare ?? row.value;
            const differs =
              !NOT_COMPARED.has(row.key) && upstream !== null && downstream !== null &&
              (cmp(upstream) ?? "") !== (cmp(downstream) ?? "");
            const focus = row.key === focusField || (focusField === "booking_status" && row.key === "status");
            const empty = row.optional ? <span className="muted">—</span> : <span className="missing">missing</span>;
            return (
              <tr key={row.key} className={`${differs ? "differs" : ""} ${focus ? "focus" : ""}`}>
                <th scope="row">
                  {row.label}
                  {focus && <span className="focus-mark" title="Field under investigation">●</span>}
                </th>
                <td>{upstream ? up ?? empty : <span className="muted">no record</span>}</td>
                <td>{downstream ? down ?? empty : <span className="muted">no record</span>}</td>
              </tr>
            );
          })}
          <tr>
            <th scope="row">Source last updated</th>
            <td>{upstream ? formatDateTime(upstream.source_updated_at) : "—"}</td>
            <td>{downstream ? formatDateTime(downstream.source_updated_at) : "—"}</td>
          </tr>
        </tbody>
      </table>
      {[upstream, downstream].some((r) => r && r.normalization_issues.length > 0) && (
        <ul className="issues">
          {[upstream, downstream].flatMap((r) =>
            r ? r.normalization_issues.map((issue, i) => (
              <li key={`${r.source_system}-${i}`}>
                <strong>{r.source_system}</strong> {String(issue.field)}: could not interpret{" "}
                <code>{JSON.stringify(issue.raw_value)}</code> ({String(issue.issue)})
              </li>
            )) : [],
          )}
        </ul>
      )}
    </div>
  );
}
