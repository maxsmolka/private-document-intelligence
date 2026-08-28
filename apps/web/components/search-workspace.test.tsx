import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResponse } from "@/lib/api/documents";

const mocks = vi.hoisted(() => ({ push: vi.fn(), save: vi.fn(), remove: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/api/documents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/documents")>()),
  saveSearch: mocks.save,
  deleteSavedSearch: mocks.remove,
}));

import { SearchWorkspace } from "@/components/search-workspace";

const data: SearchResponse = {
  schema_version: "2",
  query: "Rechnung",
  total: 1,
  limit: 25,
  offset: 0,
  results: [],
  facets: {
    document_types: [{ value: "invoice", label: "Invoice", count: 1 }],
    organizations: [{ value: "org-id", label: "Example AG", count: 1 }],
    years: [{ value: "2026", label: "2026", count: 1 }],
    review_states: [{ value: "needs_review", label: "Needs Review", count: 1 }],
    sources: [{ value: "scanner", label: "Scanner", count: 1 }],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.save.mockResolvedValue({
    id: "saved-id",
    name: "Invoices",
    filters: { q: "Rechnung" },
    created_at: "2026-08-28T00:00:00Z",
    updated_at: "2026-08-28T00:00:00Z",
  });
  mocks.remove.mockResolvedValue({ deleted: true });
});
afterEach(cleanup);

describe("SearchWorkspace structured retrieval", () => {
  it("renders facet counts as reusable filters", () => {
    render(<SearchWorkspace data={data} filters={{ q: "Rechnung" }} unavailable={false} savedSearches={[]} />);
    expect(screen.getByRole("link", { name: "Invoice · 1" })).toHaveAttribute(
      "href",
      "/search?q=Rechnung&document_type=invoice",
    );
    expect(screen.getByRole("link", { name: "Example AG · 1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Scanner · 1" })).toBeInTheDocument();
  });

  it("keeps active facet values visible when the current result set is empty", () => {
    render(<SearchWorkspace data={{ ...data, total: 0, facets: { ...data.facets, sources: [], organizations: [] } }} filters={{ source: "imap", organization_id: "missing-org" }} unavailable={false} savedSearches={[]} />);
    expect(screen.getByLabelText("Source")).toHaveValue("imap");
    expect(screen.getByLabelText("Organization")).toHaveValue("missing-org");
  });

  it("saves and deletes a user-owned query without changing results", async () => {
    render(<SearchWorkspace data={data} filters={{ q: "Rechnung" }} unavailable={false} savedSearches={[]} />);
    fireEvent.change(screen.getByLabelText("Saved search name"), { target: { value: "Invoices" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("link", { name: "Invoices" })).toBeInTheDocument();
    expect(mocks.save).toHaveBeenCalledWith("Invoices", { q: "Rechnung" });
    fireEvent.click(screen.getByRole("button", { name: "Delete Invoices" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Invoices" })).not.toBeInTheDocument());
    expect(mocks.remove).toHaveBeenCalledWith("saved-id");
  });
});
