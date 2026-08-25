import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentRecord, MetadataProposal, ReviewDetail, ReviewItem } from "@/lib/api/documents";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  confirmReview: vi.fn(),
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
  rejectReview: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock("@/components/document-preview", () => ({ DocumentPreview: () => <div>Document preview</div> }));
vi.mock("@/components/retry-processing-button", () => ({ RetryProcessingButton: () => null }));
vi.mock("@/lib/api/documents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/documents")>()),
  confirmReview: mocks.confirmReview,
  acceptProposal: mocks.acceptProposal,
  rejectProposal: mocks.rejectProposal,
  rejectReview: mocks.rejectReview,
}));

import { ReviewWorkspace } from "@/components/review-workspace";

function document(id: string, title: string): DocumentRecord {
  return {
    id, title, original_filename: `${id}.pdf`, mime_type: "application/pdf", file_size: 100,
    sha256: id.repeat(8), created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    document_date: null, status: "needs_review", life_area: "home", document_type: null,
    source: "test", canonical_metadata: {}, canonical_extraction_id: null,
  };
}

function proposal(id: string): MetadataProposal {
  return {
    id, document_id: "doc-1", field_name: "document_type", proposed_value: "rental_contract",
    normalized_value: "rental_contract", structured_value: null, source: "intelligence", provider: "deterministic",
    intelligence_run_id: "run-1", confidence: 0.95,
    evidence: [{ page: 1, start: 0, end: 11, text: "Mietvertrag", verified: true }], evidence_verified: true,
    validation_notes: [], is_critical: false, status: "pending", created_at: "2026-01-01T00:00:00Z", confirmed_at: null,
  };
}

function fixtures(): { detail: ReviewDetail; queue: ReviewItem[] } {
  const first = document("doc-1", "Synthetic lease");
  const second = document("doc-2", "Synthetic invoice");
  return {
    detail: { document: first, extraction: null, proposals: [proposal("proposal-1")], latest_job: null, assets: [], current_intelligence_run: null, metadata_history: [] },
    queue: [first, second].map((item) => ({ document: item, warnings: [], proposal_count: 1, knowledge_proposal_count: 0, extraction_review_required: false })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.confirmReview.mockResolvedValue(document("doc-1", "Synthetic lease"));
  mocks.acceptProposal.mockResolvedValue({});
});
afterEach(cleanup);

describe("ReviewWorkspace state synchronization", () => {
  it("updates completion state, queue count, and navigation immediately after review", async () => {
    const data = fixtures();
    render(<ReviewWorkspace {...data} />);

    fireEvent.click(screen.getByRole("button", { name: "Mark document reviewed" }));

    expect(await screen.findByText("Review completed · 1 remaining")).toBeInTheDocument();
    expect(screen.getByText("Review queue · 1 documents")).toBeInTheDocument();
    expect(mocks.push).toHaveBeenCalledWith("/review?id=doc-2");
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it("removes a decided metadata proposal without waiting for a route refresh", async () => {
    const data = fixtures();
    render(<ReviewWorkspace {...data} />);

    fireEvent.click(screen.getByRole("button", { name: "Accept field" }));

    await waitFor(() => expect(screen.queryByText("Evidence-backed proposals")).not.toBeInTheDocument());
    expect(screen.getByText("Metadata · 0")).toBeInTheDocument();
  });
});
