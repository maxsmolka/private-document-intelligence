import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { proxy } from "@/proxy";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("authentication proxy", () => {
  it("preserves an internal protected path through the login next parameter", () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    const response = proxy(new NextRequest("https://pdi.invalid/documents/document-id"));
    const location = response.headers.get("location");

    expect(location).not.toBeNull();
    const login = new URL(location!);
    expect(login.origin).toBe("https://pdi.invalid");
    expect(login.pathname).toBe("/login");
    expect(login.searchParams.get("next")).toBe("/documents/document-id");
  });

  it("allows an authenticated session to continue to the protected route", () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    const response = proxy(new NextRequest("https://pdi.invalid/search", {
      headers: { cookie: "pdi_session=synthetic-session" },
    }));

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
