import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/app/login/page";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

async function submitSuccessfulLogin(next: string) {
  window.history.replaceState({}, "", `/login?next=${encodeURIComponent(next)}`);
  fetchMock.mockResolvedValue({ ok: true, status: 200 });
  const navigate = vi.fn();
  render(<LoginForm navigate={navigate} />);

  fireEvent.change(screen.getByRole("textbox", { name: "Username" }), {
    target: { value: "pilot" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "correct horse battery staple" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);

  await waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/pdi/api/v1/auth/login",
    expect.objectContaining({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({
        username: "pilot",
        password: "correct horse battery staple",
      }),
    }),
  );
  return navigate;
}

describe("LoginForm post-login redirect", () => {
  it("preserves a valid internal protected-route destination", async () => {
    const navigate = await submitSuccessfulLogin("/documents/6eb3d86a?view=review#evidence");
    expect(navigate).toHaveBeenCalledWith("/documents/6eb3d86a?view=review#evidence");
  });

  it("uses the safe default for a malicious external destination", async () => {
    const navigate = await submitSuccessfulLogin("//evil.example");
    expect(navigate).toHaveBeenCalledWith("/");
  });
});
