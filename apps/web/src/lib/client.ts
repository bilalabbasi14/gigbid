// Thin hand-written wrapper over the generated client in ./api (never edit ./api by hand;
// run `make openapi-client` after changing the FastAPI schemas).
import createClient from "openapi-fetch";
import type { components, paths } from "./api/schema";

export type S = components["schemas"];

export const api = createClient<paths>({ baseUrl: "/api", credentials: "include" });

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailOf(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
  }
  return "Request failed";
}

/** Resolve an openapi-fetch call to its data or throw an ApiError with the server's detail. */
export async function call<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let res: { data?: T; error?: unknown; response: Response };
  try {
    res = await p;
  } catch {
    throw new ApiError(0, "Cannot reach the GigBid API");
  }
  if (res.error !== undefined || !res.response.ok) {
    throw new ApiError(res.response.status, detailOf(res.error));
  }
  return res.data as T;
}

export async function upload(path: string, form: FormData): Promise<unknown> {
  const r = await fetch(`/api${path}`, { method: "POST", body: form, credentials: "include" });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, detailOf(body));
  return body;
}

export function money(v: number | null | undefined, type?: string | null): string {
  if (v === null || v === undefined) return "n/a";
  const s = `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  return type === "hourly" ? `${s}/h` : s;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
