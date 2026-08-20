export type DocumentStatus =
  | "inbox"
  | "processing"
  | "ready"
  | "needs_review"
  | "archived"
  | "failed";

export type LifeArea =
  | "finance"
  | "insurance"
  | "vehicle"
  | "home"
  | "health"
  | "tax"
  | "work"
  | "travel"
  | "personal"
  | "other";

export interface DocumentRecord {
  id: string;
  title: string;
  original_filename: string;
  mime_type: string;
  file_size: number;
  sha256: string;
  created_at: string;
  updated_at: string;
  document_date: string | null;
  status: DocumentStatus;
  life_area: LifeArea;
  document_type: string | null;
  source: string;
}

export interface DocumentListResponse {
  items: DocumentRecord[];
  total: number;
  limit: number;
  offset: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function serverApiUrl() {
  return process.env.PDI_API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_PDI_API_URL ?? "http://localhost:8000";
}

export function publicApiUrl() {
  return process.env.NEXT_PUBLIC_PDI_API_URL ?? "http://localhost:8000";
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${serverApiUrl()}${path}`, { cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, `PDI API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export function getDocuments(filters?: { status?: string; lifeArea?: string }) {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.lifeArea) params.set("life_area", filters.lifeArea);
  const query = params.size ? `?${params}` : "";
  return request<DocumentListResponse>(`/api/v1/documents${query}`);
}

export function getDocument(id: string) {
  return request<DocumentRecord>(`/api/v1/documents/${encodeURIComponent(id)}`);
}

export function documentContentUrl(id: string) {
  return `${publicApiUrl()}/api/v1/documents/${encodeURIComponent(id)}/content`;
}

