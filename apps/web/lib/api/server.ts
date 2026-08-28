import "server-only";
import { cookies } from "next/headers";
import {
  ApiError,
  type DocumentListResponse, type DocumentRecord, type ExtractionHistory, type ReviewDetail,
  type ReviewListResponse, type SavedSearch, type SearchResponse,
} from "./documents";
import type {
  ActionItem, Contract, ContractDetail, Deadline, KnowledgeProposal, Organization,
  OrganizationDetail, TimelineEvent,
} from "./knowledge";

interface Page<T> { items: T[]; total: number; limit: number; offset: number }

async function serverRequest<T>(path: string): Promise<T> {
  const cookie = (await cookies()).toString();
  const base = process.env.PDI_API_INTERNAL_URL ?? "http://localhost:8000";
  const response = await fetch(`${base}${path}`, {
    cache: "no-store",
    headers: cookie ? { cookie } : undefined,
  });
  if (!response.ok) throw new ApiError(response.status, `PDI API returned ${response.status}`);
  return response.json() as Promise<T>;
}

export function getDocuments(filters?: { status?: string; lifeArea?: string }) {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.lifeArea) params.set("life_area", filters.lifeArea);
  return serverRequest<DocumentListResponse>(`/api/v1/documents${params.size ? `?${params}` : ""}`);
}
export const getDocument = (id: string) => serverRequest<DocumentRecord>(`/api/v1/documents/${encodeURIComponent(id)}`);
export const getExtractionHistory = (id: string) => serverRequest<ExtractionHistory>(`/api/v1/documents/${encodeURIComponent(id)}/extractions`);
export const getReviewQueue = () => serverRequest<ReviewListResponse>("/api/v1/review");
export const getReviewDetail = (id: string) => serverRequest<ReviewDetail>(`/api/v1/review/${encodeURIComponent(id)}`);
export function getSearch(filters: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  const names: Record<string, string> = {
    lifeArea: "life_area", documentType: "document_type", dateFrom: "date_from", dateTo: "date_to",
    organizationId: "organization_id", contractId: "contract_id", hasEvent: "has_event",
    hasDeadline: "has_deadline", amountMin: "amount_min", amountMax: "amount_max",
  };
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") params.set(names[key] ?? key, String(value));
  return serverRequest<SearchResponse>(`/api/v1/search?${params}`);
}
export const getSavedSearches = () => serverRequest<SavedSearch[]>("/api/v1/search/saved");
export const getOrganizations = () => serverRequest<Page<Organization>>("/api/v1/organizations");
export const getOrganization = (id: string) => serverRequest<OrganizationDetail>(`/api/v1/organizations/${encodeURIComponent(id)}`);
export const getContracts = () => serverRequest<Page<Contract>>("/api/v1/contracts");
export const getContract = (id: string) => serverRequest<ContractDetail>(`/api/v1/contracts/${encodeURIComponent(id)}`);
export const getTimeline = (params?: URLSearchParams) => serverRequest<Page<TimelineEvent>>(`/api/v1/timeline${params?.size ? `?${params}` : ""}`);
export const getDeadlines = () => serverRequest<Page<Deadline>>("/api/v1/deadlines?status=open");
export const getActionItems = () => serverRequest<Page<ActionItem>>("/api/v1/action-items?status=open");
export const getKnowledgeReview = (proposalType?: string) => serverRequest<Page<KnowledgeProposal>>(`/api/v1/knowledge/review${proposalType ? `?proposal_type=${encodeURIComponent(proposalType)}` : ""}`);
