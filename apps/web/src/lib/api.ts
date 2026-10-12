export type Account = {
  id: string;
  display_name: string;
  email: string;
  environment: string;
  fixtures_enabled: boolean;
};
export type Project = {
  id: string;
  title: string;
  repository_url: string;
  status: string;
  created_at: string;
};
export type Stage = {
  id: string;
  ordinal: number;
  stage_key: string;
  state: string;
  attempt_count: number;
  error_code: string | null;
};
export type Job = {
  id: string;
  project_id: string;
  project_title?: string;
  state: string;
  version: number;
  synthetic: boolean;
  fixture: string;
  error_code: string | null;
  created_at: string;
  deadline: string;
  stages?: Stage[];
  history?: { version: number; state: string; created_at: string }[];
  attempts?: {
    stage_id: string;
    attempt_no: number;
    outcome: string;
    error_code: string | null;
  }[];
  usage?: {
    event_type: string;
    units: number;
    measurements: Record<string, number>;
  }[];
};

export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
  ) {
    super(code);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const csrf =
    document.cookie
      .split("; ")
      .find((c) => c.startsWith("rv_csrf="))
      ?.slice(8) || "";
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ error: { code: "connection_failed" } }));
    throw new ApiError(body.error?.code || "request_failed", response.status);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
export const errorMessage = (error: unknown): string => {
  if (error instanceof ApiError && error.status === 401)
    return "Your session expired. Sign in to continue.";
  if (error instanceof ApiError && error.status === 429)
    return "A local quota was reached. Try again later.";
  if (error instanceof ApiError && error.status === 422)
    return "Check your input. Use a canonical GitHub repository URL.";
  return "We could not complete that request. Please try again.";
};
