/*
 * Same-origin API client. Every call goes to the Next.js proxy at /api/v1, which forwards an
 * explicit allowlist to the FastAPI service.
 *
 * CSRF: the API binds a readable `rv_csrf` cookie to the session and requires it back as
 * `X-CSRF-Token`, with an exact Origin, on every state-changing request. Safe methods carry
 * neither the token nor a JSON content type, so a GET can never be mistaken for a mutation.
 */
export type {
  Account,
  ArchitectureOutcome,
  Attempt,
  AuthProviderName,
  HistoryEntry,
  Job,
  NarrationRecord,
  Project,
  ProjectDeletion,
  Stage,
  UsageEntry,
  Video,
  VideoJob,
  VideoJobState,
  VideoMetadata,
  VideoStage,
  VoiceRecord,
} from "./types";

export const API_BASE = "/api/v1";
const CSRF_COOKIE = "rv_csrf";
const STATE_CHANGING = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
    public requestId?: string,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

export type ApiOptions = Omit<RequestInit, "body" | "headers" | "method"> & {
  method?: "GET" | "HEAD" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** A pre-serialised JSON body. */
  body?: string;
  headers?: HeadersInit;
  /**
   * A caller-owned key for an admission request. Keep the same key while retrying one
   * submission so the API returns the original job instead of creating another.
   */
  idempotencyKey?: string;
};

/** The CSRF cookie value, URL-decoded when encoded, or "" when absent. */
export function readCsrfToken(cookie: string = document.cookie): string {
  for (const part of cookie.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() !== CSRF_COOKIE) continue;
    const raw = part.slice(separator + 1).trim();
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return "";
}

export const isStateChanging = (method: string) =>
  STATE_CHANGING.has(method.toUpperCase());

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { idempotencyKey, headers: callerHeaders, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(callerHeaders);
  if (isStateChanging(method)) {
    const token = readCsrfToken();
    if (token) headers.set("X-CSRF-Token", token);
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  } else {
    // A caller cannot attach mutation-only headers to a safe request.
    headers.delete("X-CSRF-Token");
    headers.delete("Content-Type");
  }
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      method,
      credentials: "same-origin",
      headers,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("connection_failed", 0);
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const error =
      body && typeof body === "object" && "error" in body
        ? (body as { error?: { code?: unknown; request_id?: unknown } }).error
        : undefined;
    const code = typeof error?.code === "string" ? error.code : "request_failed";
    const requestId =
      typeof error?.request_id === "string"
        ? error.request_id
        : response.headers.get("x-request-id") || undefined;
    throw new ApiError(code, response.status, requestId);
  }
  if (response.status === 204 || method === "HEAD") return undefined as T;
  return (await response.json()) as T;
}
