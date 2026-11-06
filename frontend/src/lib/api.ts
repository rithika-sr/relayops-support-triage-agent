// Centralized typed API client. All browser requests go to same-origin /api (proxied to FastAPI).

export class ApiError extends Error {
  status: number;
  detail: string;
  code?: string;
  errors?: { field: string; message: string }[];

  constructor(status: number, body: { detail?: unknown; code?: string; errors?: { field: string; message: string }[] }) {
    const detail = typeof body.detail === "string" ? body.detail : `Request failed (${status})`;
    super(detail);
    this.status = status;
    this.detail = detail;
    this.code = body.code;
    this.errors = body.errors;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|; )relayops_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export async function request<T>(method: Method, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", "X-Requested-With": "relayops" };
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken();
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: "same-origin", ...init });
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try {
      data = await res.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, data);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function safeNext(target: string | null, role: string): string {
  const home = role === "customer" ? "/portal" : "/app";
  if (!target || !target.startsWith("/") || target.startsWith("//") || target.includes("\\")) return home;
  const allowed = role === "customer" ? "/portal" : "/app";
  return target.startsWith(allowed) ? target : home;
}
