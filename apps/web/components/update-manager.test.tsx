import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/security", () => ({ securityRequest: mocks.request }));

import { UpdateManager } from "@/components/update-manager";

const release = {
  version: "1.2.1", release_commit: "1".repeat(40), published_at: "2026-08-27T10:00:00Z",
  release_notes: "Safe maintenance update", release_notes_url: "https://github.com/example",
  migration_required: true, reindex_required: false, backup_required: true,
  rollback_mode: "restore_backup", backend_digest: `sha256:${"a".repeat(64)}`,
  web_digest: `sha256:${"b".repeat(64)}`, target_schema: "20260827_0014",
};
const status = {
  current_version: "1.2.0", update_channel: "manual", available_release: release,
  update_available: true, active_run: null, last_successful_check: "2026-08-27T10:00:00Z",
  last_successful_update: null, installation_mode: "operator_cli", automatic_installation: false,
};

beforeEach(() => { mocks.request.mockReset(); vi.stubGlobal("confirm", vi.fn(() => true)); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("UpdateManager", () => {
  it("distinguishes availability from safe installation and shows release metadata", async () => {
    mocks.request.mockImplementation((path: string) => Promise.resolve(path.endsWith("/history") ? [] : status));
    render(<UpdateManager />);
    expect(await screen.findByText("PDI 1.2.1 available")).toBeInTheDocument();
    expect(screen.getByText("Migration").nextSibling).toHaveTextContent("Required");
    expect(screen.getByRole("button", { name: /Review update plan/ })).toBeEnabled();
    expect(screen.queryByText("Prepared safely")).not.toBeInTheDocument();
  });

  it("requires confirmation and presents the constrained operator handoff", async () => {
    const planned = {
      id: "run-1", state: "planned", from_version: "1.2.0", to_version: "1.2.1",
      compatibility: "compatible", migration_required: true, reindex_required: false,
      backup_required: true, backup_verified: false, rollback_mode: "restore_backup",
      expected_downtime: "short", schema_before: "20260826_0013", schema_target: "20260827_0014",
      target_backend_digest: release.backend_digest, target_web_digest: release.web_digest,
      warnings: [], preflight: {}, failure_code: null, failure_message: null, operator_command: null,
      started_at: "2026-08-27T10:00:00Z", finished_at: null,
    };
    const prepared = { ...planned, state: "awaiting_execution", backup_verified: true, operator_command: "pdi update execute --run-id run-1", preflight: { result: "PASS", active_jobs: 0, queued_jobs: 2, resource_leases: 0 } };
    mocks.request
      .mockResolvedValueOnce({ ...status, active_run: planned }).mockResolvedValueOnce([])
      .mockResolvedValueOnce(prepared)
      .mockResolvedValueOnce({ ...status, active_run: prepared }).mockResolvedValueOnce([prepared]);
    render(<UpdateManager />);
    fireEvent.click(await screen.findByRole("button", { name: "Prepare and verify backup" }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(await screen.findByText("Prepared safely")).toBeInTheDocument();
    expect(screen.getByText(/pdi update execute/)).toBeInTheDocument();
  });
});
