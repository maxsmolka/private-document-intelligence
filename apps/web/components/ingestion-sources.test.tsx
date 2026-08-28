import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/security", () => ({ securityRequest: mocks.request }));

import { IngestionSourcesPanel, type IngestionSource } from "@/components/ingestion-sources";

afterEach(() => {
  cleanup();
  mocks.request.mockReset();
});

const consume: IngestionSource = {
  id: "consume-id",
  source_type: "consume",
  display_name: "Consume folder",
  enabled: true,
  health: "degraded",
  safe_configuration: { directory: "/consume", supported_types: ["PDF", "JPEG", "PNG"] },
  last_checked_at: "2026-08-28T10:00:00Z",
  last_success_at: "2026-08-28T09:00:00Z",
  last_failure_at: "2026-08-28T10:00:00Z",
  last_error: "PermissionError",
  last_report: { failed: 1 },
  ingested_document_count: 12,
  pending_work: 2,
  pending_failures: 1,
  retry_supported: true,
};

const mail: IngestionSource = {
  ...consume,
  id: "mail-id",
  source_type: "mail",
  display_name: "IMAP mailbox",
  enabled: false,
  health: "disabled",
  safe_configuration: { host: "imap.example.test", tls: true, read_only: true, credentials_configured: true },
  last_checked_at: null,
  last_success_at: null,
  last_failure_at: null,
  last_error: null,
  ingested_document_count: 0,
  pending_work: 0,
  pending_failures: 0,
};

describe("IngestionSourcesPanel", () => {
  it("shows safe source health, counts, and no credential fields", async () => {
    mocks.request.mockResolvedValueOnce([consume, mail]);
    render(<IngestionSourcesPanel />);
    expect(await screen.findByText("Consume folder")).toBeInTheDocument();
    expect(screen.getByText("IMAP mailbox")).toBeInTheDocument();
    expect(screen.getByText(/Attention required.*PermissionError/)).toBeInTheDocument();
    expect(screen.getByText("/consume")).toBeInTheDocument();
    expect(screen.queryByText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/scanner@example/i)).not.toBeInTheDocument();
  });

  it("enables a source and retries failures with authenticated actions", async () => {
    mocks.request
      .mockResolvedValueOnce([consume, mail])
      .mockResolvedValueOnce({ ...mail, enabled: true, health: "unknown" })
      .mockResolvedValueOnce({ requested: 1 })
      .mockResolvedValueOnce([consume, { ...mail, enabled: true, health: "healthy" }]);
    render(<IngestionSourcesPanel />);
    await screen.findByText("IMAP mailbox");
    fireEvent.click(screen.getByRole("button", { name: "Enable source" }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith(
      "/api/v1/ingestion/sources/mail-id/enabled",
      { method: "POST", body: JSON.stringify({ enabled: true }) },
    ));
    const retry = screen.getAllByRole("button", { name: "Retry failures" })
      .find((button) => !(button as HTMLButtonElement).disabled);
    expect(retry).toBeDefined();
    fireEvent.click(retry!);
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith(
      "/api/v1/ingestion/sources/consume-id/retry",
      { method: "POST" },
    ));
    expect(await screen.findByRole("status")).toHaveTextContent("1 failed item queued for retry.");
  });
});
