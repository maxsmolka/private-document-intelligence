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
  canonical_metadata: Record<string, unknown>;
}

export interface DocumentListResponse {
  items: DocumentRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface IngestionJob {
  id: string;
  document_id: string;
  state: "queued" | "claimed" | "extracting" | "ocr" | "normalizing" | "completed" | "failed";
  stage: string;
  attempt_count: number;
  max_attempts: number;
  available_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error_category: string | null;
  last_error: string | null;
}

export interface DocumentExtraction {
  id: string;
  document_id: string;
  provider: string;
  provider_version: string;
  method: string;
  text: string;
  page_count: number;
  pages: string[];
  language: string | null;
  content_hash: string;
  warnings: string[];
  extraction_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MetadataProposal {
  id: string;
  document_id: string;
  field_name: string;
  proposed_value: string | null;
  normalized_value: string | null;
  structured_value: Record<string, unknown> | unknown[] | null;
  source: string;
  provider: string | null;
  intelligence_run_id: string | null;
  confidence: number | null;
  evidence: Array<{ page: number; start: number; end: number; text: string; verified: boolean }>;
  evidence_verified: boolean;
  validation_notes: string[];
  is_critical: boolean;
  status: "pending" | "accepted" | "rejected" | "superseded";
  created_at: string;
  confirmed_at: string | null;
}

export interface DocumentAsset {
  id: string;
  document_id: string;
  kind: "original" | "ocr_pdf";
  mime_type: string;
  file_size: number;
  sha256: string;
  provider: string;
  provider_version: string;
  created_at: string;
  updated_at: string;
}

export interface ReviewItem {
  document: DocumentRecord;
  warnings: string[];
  proposal_count: number;
}

export interface ReviewListResponse {
  items: ReviewItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReviewDetail {
  document: DocumentRecord;
  extraction: DocumentExtraction | null;
  proposals: MetadataProposal[];
  latest_job: IngestionJob | null;
  assets: DocumentAsset[];
  current_intelligence_run: IntelligenceRun | null;
  metadata_history: CanonicalMetadataHistory[];
}

export interface IntelligenceRun {
  id: string;
  document_id: string;
  input_extraction_id: string;
  input_content_hash: string;
  provider: string;
  provider_version: string;
  schema_version: string;
  prompt_version: string | null;
  status: "running" | "completed" | "failed";
  is_current: boolean;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error_category: string | null;
  sanitized_error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
}

export interface CanonicalMetadataHistory {
  id: string;
  document_id: string;
  field_name: string;
  previous_value: unknown;
  new_value: unknown;
  source_proposal_id: string | null;
  confirmation_source: string;
  confirmed_at: string;
}

export interface ConfirmMetadata {
  title: string;
  document_date: string | null;
  life_area: LifeArea;
  document_type: string | null;
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

async function mutate<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`${publicApiUrl()}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    let message = `PDI API returned ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch { /* response was not JSON */ }
    throw new ApiError(response.status, message);
  }
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

export function getReviewQueue() {
  return request<ReviewListResponse>("/api/v1/review");
}

export function getReviewDetail(id: string) {
  return request<ReviewDetail>(`/api/v1/review/${encodeURIComponent(id)}`);
}

export function confirmReview(id: string, values: ConfirmMetadata) {
  return mutate<DocumentRecord>(`/api/v1/review/${encodeURIComponent(id)}/confirm`, values);
}

export function rejectReview(id: string) {
  return mutate<MetadataProposal[]>(`/api/v1/review/${encodeURIComponent(id)}/reject`);
}

export function acceptProposal(documentId: string, proposalId: string, value?: string) {
  return mutate<DocumentRecord>(
    `/api/v1/review/${encodeURIComponent(documentId)}/proposals/${encodeURIComponent(proposalId)}/accept`,
    value === undefined ? {} : { value },
  );
}

export function rejectProposal(documentId: string, proposalId: string) {
  return mutate<MetadataProposal>(
    `/api/v1/review/${encodeURIComponent(documentId)}/proposals/${encodeURIComponent(proposalId)}/reject`,
  );
}

export function retryDocument(id: string) {
  return mutate<IngestionJob>(`/api/v1/documents/${encodeURIComponent(id)}/retry`);
}

export function documentContentUrl(id: string) {
  return `${publicApiUrl()}/api/v1/documents/${encodeURIComponent(id)}/content`;
}
