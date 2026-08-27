import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/security", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/security")>()),
  securityRequest: mocks.request,
}));

import { AboutPanel, AccountPanel, SecurityPanel, SessionsPanel, TokensPanel } from "@/components/settings-panels";

beforeEach(() => {
  mocks.request.mockReset();
  vi.stubGlobal("confirm", vi.fn(() => true));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("security settings state synchronization", () => {
  it("shows password mutation success immediately", async () => {
    mocks.request.mockResolvedValue({ changed: true });
    render(<AccountPanel />);
    for (const [label, value] of [
      ["Current password", "current safe password"],
      ["New password", "new safe password value"],
      ["Confirm new password", "new safe password value"],
    ]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(/All previous sessions were revoked/)).toBeInTheDocument();
  });

  it("removes a revoked session without a page refresh", async () => {
    mocks.request
      .mockResolvedValueOnce([
        { id: "current", created_at: "2026-08-26T00:00:00Z", last_seen_at: "2026-08-26T00:00:00Z", expires_at: "2026-08-27T00:00:00Z", current: true },
        { id: "other", created_at: "2026-08-25T00:00:00Z", last_seen_at: "2026-08-25T00:00:00Z", expires_at: "2026-08-27T00:00:00Z", current: false },
      ])
      .mockResolvedValueOnce({ revoked: true })
      .mockResolvedValueOnce([
        { id: "current", created_at: "2026-08-26T00:00:00Z", last_seen_at: "2026-08-26T00:00:00Z", expires_at: "2026-08-27T00:00:00Z", current: true },
      ]);
    render(<SessionsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(screen.queryByText("Browser session")).not.toBeInTheDocument());
    expect(mocks.request).toHaveBeenCalledWith("/api/v1/account/sessions/other/revoke", { method: "POST" });
  });

  it("shows newly created token plaintext exactly in the creation result", async () => {
    mocks.request
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ id: "token", name: "Test", prefix: "pdi_prefix", scopes: ["documents:read"], created_at: "2026-08-26T00:00:00Z", last_used_at: null, revoked: false, token: "pdi_plaintext_once" })
      .mockResolvedValueOnce([{ id: "token", name: "Test", prefix: "pdi_prefix", scopes: ["documents:read"], created_at: "2026-08-26T00:00:00Z", last_used_at: null, revoked: false }]);
    render(<TokensPanel />);
    await waitFor(() => expect(mocks.request).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText("Token name"), { target: { value: "Test" } });
    fireEvent.click(screen.getByLabelText("documents:read"));
    fireEvent.click(screen.getByRole("button", { name: /Create token/ }));
    expect(await screen.findByText("pdi_plaintext_once")).toBeInTheDocument();
    expect(await screen.findByText(/pdi_prefix/)).toBeInTheDocument();
  });

  it("renders an explicit backend/web mismatch warning", async () => {
    mocks.request.mockResolvedValue({
      product_version: "1.1.0", backend: { version: "1.1.0", revision: "a", build_time: "now" },
      web: { version: "1.0.2", revision: "b", build_time: "then" }, database: { alembic_revision: "20260826_0012" },
      runtime: { platform: "Linux", architecture: "x86_64", deployment_type: "container" },
      ocr: { provider: "ocrmypdf", ocrmypdf_version: "16", tesseract_version: "5" }, intelligence: { provider: "deterministic", model: null },
      version_consistent: false, revision_consistent: false, warnings: ["Backend version 1.1.0 does not match web version 1.0.2."],
      update: { channel: "manual", available_version: null, update_available: false, last_checked_at: null },
    });
    render(<AboutPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  });

  it("requires confirmation before disabling two-factor authentication", async () => {
    vi.mocked(window.confirm).mockReturnValue(false);
    mocks.request.mockResolvedValue({ enabled: true, pending_setup: false, recovery_codes_remaining: 10, encryption_configured: true });
    render(<SecurityPanel />);
    await screen.findByText(/Enabled · 10 recovery codes remain/);
    fireEvent.change(screen.getAllByLabelText("Current password")[1], { target: { value: "safe current password" } });
    fireEvent.change(screen.getAllByLabelText("Authenticator code")[1], { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Disable 2FA" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mocks.request).toHaveBeenCalledTimes(1);
  });
});
