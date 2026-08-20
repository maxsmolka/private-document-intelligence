import { mutate, request, type LifeArea } from "./documents";

export interface Organization {
  id: string; canonical_name: string; normalized_name: string; organization_type: string | null;
  status: "active" | "inactive" | "merged"; merged_into_id: string | null; source_document_id: string | null;
  evidence: Evidence[]; created_at: string; updated_at: string;
}
export interface OrganizationDetail extends Organization {
  aliases: string[]; document_ids: string[]; contract_ids: string[]; event_ids: string[];
  deadline_ids: string[]; action_item_ids: string[];
}
export interface Contract {
  id: string; title: string; contract_type: string; status: string; organization_id: string | null;
  reference_identifier: string | null; start_date: string | null; end_date: string | null;
  renewal_date: string | null; cancellation_deadline: string | null; source_document_id: string | null;
  evidence: Evidence[]; created_at: string; updated_at: string;
}
export interface ContractDetail extends Contract {
  organization: Organization | null; documents: Array<{ document_id: string; relationship_type: string }>;
  event_ids: string[]; deadline_ids: string[]; action_item_ids: string[];
}
export interface Evidence { page: number; start: number; end: number; text: string; verified: boolean }
export interface TimelineEvent {
  id: string; event_type: string; title: string; description: string | null; event_date: string | null;
  event_date_precision: string; life_area: LifeArea; organization_id: string | null; contract_id: string | null;
  source_document_id: string; evidence: Evidence[]; created_at: string;
}
export interface Deadline {
  id: string; title: string; due_at: string | null; original_rule: string | null; deadline_type: string;
  status: string; organization_id: string | null; contract_id: string | null; source_document_id: string;
  evidence: Evidence[]; created_at: string; updated_at: string;
}
export interface ActionItem {
  id: string; title: string; description: string | null; status: string; due_at: string | null;
  priority: string; life_area: LifeArea; organization_id: string | null; contract_id: string | null;
  deadline_id: string | null; source_document_id: string; evidence: Evidence[]; completed_at: string | null;
}
export interface KnowledgeProposal {
  id: string; proposal_type: string; document_id: string; payload: Record<string, unknown>; confidence: number;
  evidence: Evidence[]; evidence_verified: boolean; validation_notes: string[];
  possible_existing_organization_id: string | null; match_reason: string | null; status: string;
}
interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export const getOrganizations = () => request<Page<Organization>>("/api/v1/organizations");
export const getOrganization = (id: string) => request<OrganizationDetail>(`/api/v1/organizations/${encodeURIComponent(id)}`);
export const getContracts = () => request<Page<Contract>>("/api/v1/contracts");
export const getContract = (id: string) => request<ContractDetail>(`/api/v1/contracts/${encodeURIComponent(id)}`);
export const getTimeline = (params?: URLSearchParams) => request<Page<TimelineEvent>>(`/api/v1/timeline${params?.size ? `?${params}` : ""}`);
export const getDeadlines = () => request<Page<Deadline>>("/api/v1/deadlines?status=open");
export const getActionItems = () => request<Page<ActionItem>>("/api/v1/action-items?status=open");
export const getKnowledgeReview = () => request<Page<KnowledgeProposal>>("/api/v1/knowledge/review");
export const acceptKnowledge = (id: string, target?: string, values: Record<string, unknown> = {}) => mutate<KnowledgeProposal>(
  `/api/v1/knowledge/review/${encodeURIComponent(id)}/accept`,
  target ? { action: "link_existing", target_resource_id: target, values } : { action: "create", values },
);
export const rejectKnowledge = (id: string) => mutate<KnowledgeProposal>(`/api/v1/knowledge/review/${encodeURIComponent(id)}/reject`);
export const updateAction = (id: string, status: "completed" | "dismissed") => mutate<ActionItem>(`/api/v1/action-items/${encodeURIComponent(id)}/status`, { status });
export const updateDeadline = (id: string, status: "completed" | "dismissed") => mutate<Deadline>(`/api/v1/deadlines/${encodeURIComponent(id)}/status`, { status });
