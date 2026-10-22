// Thin API client. Every backend call goes through request(): one place for
// timeouts, error parsing and JSON handling. The browser only ever talks to
// the backend (/api/*); it never calls Ollama directly.

import type {
  AiStatus,
  AuditEvent,
  EvidencePackage,
  EvidenceTrace,
  ExceptionCounts,
  ExceptionDetail,
  ExceptionSummary,
  HealthResponse,
  InvestigationAudit,
  InvestigationSummary,
  Resolution,
  ResolutionInput,
  ResolutionOptions,
  ValidationRun,
} from "./types";

export type { HealthResponse } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
    public readonly reference?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const DEFAULT_TIMEOUT_MS = 15_000;
// A local model on CPU can take minutes per attempt, with up to 2 attempts.
export const INVESTIGATION_TIMEOUT_MS = 25 * 60_000;

function errorFrom(status: number, data: unknown): ApiError {
  const detail = data !== null && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;

  if (typeof detail === "string" && detail) return new ApiError(detail, status);

  if (Array.isArray(detail)) {
    // FastAPI/Pydantic validation errors: [{loc: [...], msg: "..."}]
    const message = detail
      .map((d) => {
        if (d !== null && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown }).loc) ? ((d as { loc: unknown[] }).loc.slice(1).join(".")) : "";
          return loc ? `${loc}: ${String((d as { msg: unknown }).msg)}` : String((d as { msg: unknown }).msg);
        }
        return String(d);
      })
      .join("; ");
    return new ApiError(message || `Request rejected (HTTP ${status})`, status);
  }

  if (detail !== null && typeof detail === "object" && "message" in detail) {
    const d = detail as { message: unknown; error_code?: unknown; investigation_id?: unknown };
    return new ApiError(
      String(d.message),
      status,
      typeof d.error_code === "string" ? d.error_code : undefined,
      typeof d.investigation_id === "string" ? d.investigation_id : undefined,
    );
  }
  return new ApiError(`Backend returned HTTP ${status}`, status);
}

export async function request<T>(
  method: "GET" | "POST" | "PATCH",
  path: string,
  body?: unknown,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(`No response from the backend within ${Math.round(timeoutMs / 1000)}s`);
    }
    throw new ApiError("Could not reach the backend. Is it running on port 8000?");
  } finally {
    window.clearTimeout(timer);
  }

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) throw errorFrom(response.status, data);
  return data as T;
}

const enc = encodeURIComponent;

function query(params: Record<string, string | boolean | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "" && v !== false)
    .map(([k, v]) => `${enc(k)}=${enc(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export const api = {
  health: () => request<HealthResponse>("GET", "/api/health", undefined, 5000),

  exceptionCounts: () => request<ExceptionCounts>("GET", "/api/exceptions/summary"),
  exceptions: (filters: { status?: string; severity?: string; category?: string; loan_id?: string; active_only?: boolean }) =>
    request<ExceptionSummary[]>("GET", `/api/exceptions${query(filters)}`),
  exception: (id: string) => request<ExceptionDetail>("GET", `/api/exceptions/${enc(id)}`),
  changeStatus: (id: string, to_status: string, actor: string, reason: string | null) =>
    request<ExceptionDetail>("PATCH", `/api/exceptions/${enc(id)}/status`, { to_status, actor, reason }),
  runValidation: () => request<ValidationRun>("POST", "/api/validation/run", undefined, 60_000),

  evidencePackage: (id: string) => request<EvidencePackage>("GET", `/api/exceptions/${enc(id)}/evidence`),
  evidence: (evidenceId: string) => request<EvidenceTrace>("GET", `/api/evidence/${enc(evidenceId)}`),

  aiStatus: () => request<AiStatus>("GET", "/api/ai/status"),
  investigations: (id: string) => request<InvestigationSummary[]>("GET", `/api/exceptions/${enc(id)}/investigations`),
  investigation: (investigationId: string) =>
    request<InvestigationAudit>("GET", `/api/investigations/${enc(investigationId)}`),
  investigate: (id: string, requested_by: string) =>
    request<InvestigationSummary>("POST", `/api/exceptions/${enc(id)}/investigations`, { requested_by }, INVESTIGATION_TIMEOUT_MS),

  resolutionOptions: () => request<ResolutionOptions>("GET", "/api/resolution/options"),
  resolution: (id: string) => request<Resolution>("GET", `/api/exceptions/${enc(id)}/resolution`),
  resolve: (id: string, input: ResolutionInput) => request<Resolution>("POST", `/api/exceptions/${enc(id)}/resolution`, input),
  audit: (id: string) => request<AuditEvent[]>("GET", `/api/exceptions/${enc(id)}/audit`),
};

// Kept for the Phase 0 health check.
export function fetchHealth(): Promise<HealthResponse> {
  return api.health();
}
