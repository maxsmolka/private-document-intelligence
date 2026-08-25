import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeProposal } from "@/lib/api/knowledge";

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), accept: vi.fn(), reject: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock("@/lib/api/knowledge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/knowledge")>()),
  acceptKnowledge: mocks.accept,
  rejectKnowledge: mocks.reject,
}));

import { KnowledgeReviewWorkspace } from "@/components/knowledge-review-workspace";

const proposalTypes = ["organization", "contract", "document_relationship", "event", "deadline", "action_item", "merge"];
function proposal(proposalType: string, verified = true): KnowledgeProposal {
  return {
    id: `proposal-${proposalType}`, proposal_type: proposalType, document_id: "synthetic-document",
    payload: proposalType === "organization" ? { canonical_name: `Synthetic ${proposalType}` } : { title: `Synthetic ${proposalType}`, relationship_type: "statement" },
    confidence: 0.9, evidence: [{ page: 1, start: 0, end: 9, text: "Synthetic", verified }], evidence_verified: verified,
    validation_notes: [], possible_existing_organization_id: null, match_reason: null, status: "pending",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.accept.mockResolvedValue({});
  mocks.reject.mockResolvedValue({});
});
afterEach(cleanup);

describe("KnowledgeReviewWorkspace action integrity", () => {
  it.each(proposalTypes.slice(0, -1))(
    "supports edit and accept for the %s proposal type",
    async (proposalType) => {
      render(<KnowledgeReviewWorkspace proposals={[proposal(proposalType)]} />);

      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "Reviewed value" } });
      fireEvent.click(screen.getByRole("button", { name: "Accept" }));

      await waitFor(() => expect(mocks.accept).toHaveBeenCalledTimes(1));
      expect(await screen.findByText("No knowledge proposals await review.")).toBeInTheDocument();
    },
  );

  it("persists rejection and removes every proposal type from local state", async () => {
    render(<KnowledgeReviewWorkspace proposals={proposalTypes.map((type) => proposal(type))} />);

    for (const type of proposalTypes) {
      fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[0]);
      await waitFor(() => expect(mocks.reject).toHaveBeenCalledWith(`proposal-${type}`));
    }

    expect(await screen.findByText("No knowledge proposals await review.")).toBeInTheDocument();
    expect(mocks.reject).toHaveBeenCalledTimes(proposalTypes.length);
  });

  it("does not advertise accept or edit for a non-actionable merge proposal", () => {
    render(<KnowledgeReviewWorkspace proposals={[proposal("merge")]} />);
    const article = screen.getByText("Synthetic merge").closest("article");
    expect(article).not.toBeNull();
    expect(within(article!).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(within(article!).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(article!).getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("keeps rejection available when source evidence is not verified", () => {
    render(<KnowledgeReviewWorkspace proposals={[proposal("deadline", false)]} />);
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });
});
