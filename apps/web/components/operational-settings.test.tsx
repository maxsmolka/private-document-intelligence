import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/security", () => ({ securityRequest: mocks.request }));

import { OperationalSettingsPanel } from "@/components/operational-settings";

afterEach(() => { cleanup(); mocks.request.mockReset(); vi.restoreAllMocks(); });

const payload = {
  restart_required: false,
  domains: [
    { key: "general", settings: [] },
    { key: "documents", settings: [] },
    { key: "ocr", settings: [{ key: "ocr_enabled", label: "OCR policy", description: "Run OCR automatically.", classification: "B", value: false, default_value: false, source: "deployment", requires_restart: false, input_kind: "boolean", minimum: null, maximum: null, options: [], updated_at: null }] },
    { key: "intelligence", settings: [] },
    { key: "ingestion", settings: [] },
    { key: "search", settings: [] },
    { key: "execution", settings: [{ key: "worker_concurrency", label: "Worker concurrency", description: "Parallel slots.", classification: "B", value: 1, default_value: 1, source: "runtime", requires_restart: true, input_kind: "integer", minimum: 1, maximum: 4, options: [], updated_at: "2026-08-28T10:00:00Z" }] },
    { key: "backup", settings: [] },
    { key: "updates", settings: [] },
    { key: "notifications", settings: [] },
    { key: "security", settings: [] },
    { key: "system", settings: [] },
  ],
};

describe("OperationalSettingsPanel", () => {
  it("shows every domain while keeping deployment secrets out of the UI", async () => {
    mocks.request.mockResolvedValueOnce(payload);
    render(<OperationalSettingsPanel />);
    expect(await screen.findByRole("button", { name: "OCR" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backup" })).toBeInTheDocument();
    expect(screen.queryByText(/database_url|password|token file/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText(/PostgreSQL full-text search is authoritative/)).toBeInTheDocument();
  });

  it("saves changed values and identifies immediate application", async () => {
    mocks.request.mockResolvedValueOnce(payload).mockResolvedValueOnce({ changed: ["ocr_enabled"], restart_required: false }).mockResolvedValueOnce({ ...payload, domains: payload.domains.map((domain) => domain.key === "ocr" ? { ...domain, settings: domain.settings.map((setting) => ({ ...setting, value: true, source: "runtime" })) } : domain) });
    render(<OperationalSettingsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "OCR" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith("/api/v1/admin/settings/ocr", { method: "PUT", body: JSON.stringify({ values: { ocr_enabled: true } }) }));
    expect(await screen.findByRole("status")).toHaveTextContent("New work uses the updated policy immediately");
  });

  it("resets runtime overrides to safe deployment defaults", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.request.mockResolvedValueOnce(payload).mockResolvedValueOnce({ changed: ["worker_concurrency"], restart_required: true }).mockResolvedValueOnce(payload);
    render(<OperationalSettingsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Execution" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset to safe defaults" }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith("/api/v1/admin/settings/execution/reset", { method: "POST" }));
  });
});
