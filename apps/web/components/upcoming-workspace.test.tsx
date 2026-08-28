import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Deadline, UpcomingSnapshot } from "@/lib/api/knowledge";

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), deadline: vi.fn(), action: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));
vi.mock("@/lib/api/knowledge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/knowledge")>()),
  updateDeadline: mocks.deadline,
  updateAction: mocks.action,
}));

import { UpcomingWorkspace } from "@/components/upcoming-workspace";

const deadline: Deadline = {
  id: "deadline-1", title: "Pay invoice", due_at: "2026-08-28", original_rule: null,
  deadline_type: "payment", status: "open", state: "due", snoozed_until: null,
  completed_at: null, organization_id: null, contract_id: null, source_document_id: "document-1",
  evidence: [{ page: 2, start: 0, end: 3, text: "pay", verified: true }],
  created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-20T00:00:00Z",
};
const snapshot: UpcomingSnapshot = {
  generated_on: "2026-08-28", overdue: [], today: [deadline], next_7_days: [],
  next_30_days: [], future: [], snoozed: [], actions: [], notifications: [],
};

beforeEach(() => { vi.clearAllMocks(); mocks.deadline.mockResolvedValue({ ...deadline, status: "completed", state: "completed" }); });
afterEach(cleanup);

describe("UpcomingWorkspace", () => {
  it("groups deadlines, links exact evidence, and completes explicitly", async () => {
    render(<UpcomingWorkspace snapshot={snapshot} pending={0} />);
    expect(screen.getByRole("heading", { name: /Today/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evidence · page 2" })).toHaveAttribute(
      "href", "/documents/document-1?page=2",
    );
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(mocks.deadline).toHaveBeenCalledWith("deadline-1", "completed", undefined));
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it("snoozes with a future date and never triggers external delivery", async () => {
    render(<UpcomingWorkspace snapshot={snapshot} pending={0} />);
    fireEvent.click(screen.getByRole("button", { name: "Snooze 7 days" }));
    await waitFor(() => expect(mocks.deadline).toHaveBeenCalled());
    const [, status, until] = mocks.deadline.mock.calls[0];
    expect(status).toBe("snoozed");
    expect(until).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
