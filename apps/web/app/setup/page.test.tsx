import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SetupWizard } from "@/app/setup/page";

const fetchMock = vi.fn();

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function openWizard(navigate = vi.fn()) {
  fetchMock.mockResolvedValueOnce(jsonResponse({ setup_required: true }));
  render(<SetupWizard navigate={navigate} />);
  await screen.findByRole("heading", { name: "Welcome to PDI" });
  fireEvent.click(screen.getByRole("button", { name: "Create the first administrator" }));
  return navigate;
}

function fillAdmin(password = "correct horse battery staple", confirmation = password) {
  fireEvent.change(screen.getByRole("textbox", { name: "Username" }), { target: { value: "owner" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: confirmation } });
  fireEvent.click(screen.getByRole("button", { name: "Create administrator" }));
}

describe("first-run setup wizard", () => {
  it("validates password confirmation before submitting", async () => {
    await openWizard();
    fillAdmin(undefined, "different password value");
    expect(await screen.findByRole("alert")).toHaveTextContent("Password confirmation does not match");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("creates the administrator and supports skipping optional TOTP", async () => {
    const navigate = await openWizard();
    fetchMock.mockResolvedValueOnce(jsonResponse({ username: "owner", role: "admin", active: true, totp_available: true }, 201));
    fillAdmin();
    await screen.findByRole("heading", { name: "Secure your account" });
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/pdi/api/v1/setup/admin",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Set up later" }));
    await screen.findByRole("heading", { name: "PDI is ready" });
    fireEvent.click(screen.getByRole("button", { name: "Continue to PDI" }));
    expect(navigate).toHaveBeenCalledWith("/");
  });

  it("reuses the account TOTP endpoints and shows one-time recovery codes", async () => {
    await openWizard();
    fetchMock.mockResolvedValueOnce(jsonResponse({ totp_available: true }, 201));
    fillAdmin();
    await screen.findByRole("heading", { name: "Secure your account" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ secret: "MANUALSECRET", qr_svg_base64: "PHN2Zy8+", provisioning_uri: "otpauth://test", expires_at: "2026-08-26T20:00:00Z" }));
    fireEvent.change(screen.getByLabelText("Confirm your administrator password"), { target: { value: "correct horse battery staple" } });
    fireEvent.click(screen.getByRole("button", { name: "Set up authenticator" }));
    await screen.findByText("MANUALSECRET");
    const codes = ["AAAA-BBBB", "CCCC-DDDD"];
    fetchMock.mockResolvedValueOnce(jsonResponse({ recovery_codes: codes, shown_once: true }));
    fireEvent.change(screen.getByLabelText("Administrator password"), { target: { value: "correct horse battery staple" } });
    fireEvent.change(screen.getByLabelText("6-digit authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Enable two-factor authentication" }));
    expect(await screen.findByText("AAAA-BBBB")).toBeInTheDocument();
    expect(screen.getByText("CCCC-DDDD")).toBeInTheDocument();
  });

  it("redirects safely when another browser completed setup", async () => {
    const navigate = await openWizard();
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Setup is unavailable" }, 409));
    fillAdmin();
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login"));
  });

  it("redirects setup when authoritative status is already complete", async () => {
    const navigate = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ setup_required: false }));
    render(<SetupWizard navigate={navigate} />);
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/login"));
  });

  it("allows setup completion when the deployment TOTP key is unavailable", async () => {
    await openWizard();
    fetchMock.mockResolvedValueOnce(jsonResponse({ totp_available: false }, 201));
    fillAdmin();
    expect(await screen.findByText(/server encryption key/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up later" })).toBeEnabled();
  });
});
