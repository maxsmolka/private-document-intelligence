import { browserApiUrl } from "@/lib/api/documents";

export type SessionInfo = { username: string; role: "admin" | "user" | "read_only"; two_factor_enabled: boolean };
export type TwoFactorStatus = { enabled: boolean; pending_setup: boolean; recovery_codes_remaining: number; encryption_configured: boolean };
export type SessionItem = { id: string; created_at: string; last_seen_at: string; expires_at: string; current: boolean };
export type TokenItem = { id: string; name: string; prefix: string; scopes: string[]; created_at: string; last_used_at: string | null; revoked: boolean; token?: string; shown_once?: boolean };
export type UserItem = { id: string; username: string; role: "admin" | "user" | "read_only"; is_active: boolean; two_factor_enabled: boolean; created_at: string; last_login_at: string | null };
export type SystemInfo = {
  product_version: string;
  backend: { version: string; revision: string; build_time: string };
  web: { version: string | null; revision: string | null; build_time: string | null };
  database: { alembic_revision: string | null };
  runtime: { platform: string; architecture: string; deployment_type: string };
  ocr: { provider: string; ocrmypdf_version: string | null; tesseract_version: string | null };
  intelligence: { provider: string; model: string | null };
  version_consistent: boolean;
  revision_consistent: boolean | null;
  warnings: string[];
  update: { channel: string; available_version: string | null; update_available: boolean; last_checked_at: string | null };
};

function csrfToken() {
  const value = document.cookie.split("; ").find((item) => item.startsWith("pdi_csrf="))?.split("=")[1];
  return value ? decodeURIComponent(value) : "";
}

export async function securityRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") headers.set("x-csrf-token", csrfToken());
  if (options.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  const response = await fetch(browserApiUrl(path), { ...options, method, headers, credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}
