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
  canonical_extraction_id: string | null;
}

export interface DocumentListResponse {
  items: DocumentRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentUploadResult {
  document: DocumentRecord;
  created: boolean;
  duplicate: boolean;
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
  source: string;
  provider: string;
  provider_version: string;
  method: string;
  text: string;
  normalized_text: string;
  page_count: number;
  pages: string[];
  language: string | null;
  content_hash: string;
  warnings: string[];
  extraction_metadata: Record<string, unknown>;
  source_provenance: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ExtractionVersion {
  id: string;
  document_id: string;
  source: string;
  provider: string;
  provider_version: string;
  method: string;
  page_count: number;
  language: string | null;
  content_hash: string;
  normalized_content_hash: string;
  character_count: number;
  warnings: string[];
  source_provenance: Record<string, unknown>;
  created_at: string;
  canonical: boolean;
}

export interface ExtractionComparison {
  id: string;
  document_id: string;
  baseline_extraction_id: string;
  candidate_extraction_id: string;
  status: "equivalent" | "review_required";
  metrics: {
    normalized_hash_equal?: boolean;
    baseline_characters?: number;
    candidate_characters?: number;
    baseline_pages?: number;
    candidate_pages?: number;
    candidate_non_whitespace_coverage?: number | null;
    similarity?: number;
    critical_field_preservation?: number | null;
    meaningful_differences?: Record<"amounts" | "dates" | "identifiers", {
      missing: string[];
      added: string[];
      missing_count: number;
      added_count: number;
      unchanged_count: number;
    }>;
  };
  review_decision: "keep_current" | "promote_candidate" | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface ExtractionPromotion {
  id: string;
  document_id: string;
  previous_extraction_id: string | null;
  promoted_extraction_id: string;
  comparison_id: string | null;
  reason: string;
  actor: string;
  reanalysis_required: boolean;
  created_at: string;
}

export interface ExtractionHistory {
  canonical_extraction_id: string | null;
  versions: ExtractionVersion[];
  comparisons: ExtractionComparison[];
  promotions: ExtractionPromotion[];
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
  kind: "original" | "ocr_pdf" | "migrated_archive";
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
  knowledge_proposal_count: number;
  extraction_review_required: boolean;
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

export interface SearchHighlightRange {
  start: number;
  end: number;
}

export interface SearchSnippet {
  page: number;
  text: string;
  highlight_ranges: SearchHighlightRange[];
}

export interface SearchResult {
  document_id: string;
  title: string;
  document_type: string | null;
  life_area: LifeArea;
  document_date: string | null;
  status: DocumentStatus;
  score: number;
  matched_fields: Array<"title" | "organization" | "identifier" | "canonical_metadata" | "text">;
  snippets: SearchSnippet[];
}

export interface SearchResponse {
  schema_version: "2";
  query: string;
  total: number;
  limit: number;
  offset: number;
  results: SearchResult[];
  facets: SearchFacets;
}

export interface SearchFacet { value: string; label: string; count: number }
export interface SearchFacets {
  document_types: SearchFacet[];
  organizations: SearchFacet[];
  years: SearchFacet[];
  review_states: SearchFacet[];
  sources: SearchFacet[];
}

export interface SavedSearch {
  id: string;
  name: string;
  filters: Record<string, string | boolean | number>;
  created_at: string;
  updated_at: string;
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

export function browserApiUrl(path: string) {
  return `/api/pdi${path}`;
}

export async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${serverApiUrl()}${path}`, { cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, `PDI API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export async function mutate<T>(path: string, body?: object): Promise<T> {
  const csrf = document.cookie.split("; ").find((value) => value.startsWith("pdi_csrf="))?.split("=")[1];
  const response = await fetch(browserApiUrl(path), {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json", ...(csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {}) },
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

export function getSearch(filters: {
  q?: string;
  limit?: number;
  offset?: number;
  status?: string;
  lifeArea?: string;
  documentType?: string;
  dateFrom?: string;
  dateTo?: string;
  organizationId?: string;
  contractId?: string;
  hasEvent?: boolean;
  hasDeadline?: boolean;
  amountMin?: string;
  amountMax?: string;
  source?: string;
  tag?: string;
}) {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  if (filters.status) params.set("status", filters.status);
  if (filters.lifeArea) params.set("life_area", filters.lifeArea);
  if (filters.documentType) params.set("document_type", filters.documentType);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  if (filters.organizationId) params.set("organization_id", filters.organizationId);
  if (filters.contractId) params.set("contract_id", filters.contractId);
  if (filters.hasEvent) params.set("has_event", "true");
  if (filters.hasDeadline) params.set("has_deadline", "true");
  if (filters.amountMin) params.set("amount_min", filters.amountMin);
  if (filters.amountMax) params.set("amount_max", filters.amountMax);
  if (filters.source) params.set("source", filters.source);
  if (filters.tag) params.set("tag", filters.tag);
  return request<SearchResponse>(`/api/v1/search?${params}`);
}

export function saveSearch(name: string, filters: Record<string, string | boolean | number>) {
  return mutate<SavedSearch>("/api/v1/search/saved", { name, filters });
}

export function deleteSavedSearch(id: string) {
  return mutate<{ deleted: boolean }>(`/api/v1/search/saved/${encodeURIComponent(id)}/delete`);
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

export async function getReviewDetailClient(id: string): Promise<ReviewDetail> {
  const response = await fetch(browserApiUrl(`/api/v1/review/${encodeURIComponent(id)}`), {
    cache: "no-store",
    credentials: "include",
  });
  if (!response.ok) throw new ApiError(response.status, `PDI API returned ${response.status}`);
  return response.json() as Promise<ReviewDetail>;
}

export function promoteExtraction(
  documentId: string,
  extractionId: string,
  comparisonId: string | null,
) {
  return mutate<ExtractionPromotion>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/extractions/${encodeURIComponent(extractionId)}/promote`,
    { comparison_id: comparisonId, reason: "user_review" },
  );
}

export function keepCurrentExtraction(documentId: string, comparisonId: string) {
  return mutate<ExtractionComparison>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/extractions/comparisons/${encodeURIComponent(comparisonId)}/keep`,
  );
}

export function documentContentUrl(id: string) {
  return browserApiUrl(`/api/v1/documents/${encodeURIComponent(id)}/content`);
}
