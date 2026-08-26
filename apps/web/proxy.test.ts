import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { proxy } from "@/proxy";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("authentication proxy", () => {
  it("preserves an internal protected path through the login next parameter", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ setup_required: false }), { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/documents/document-id"));
    const location = response.headers.get("location");

    expect(location).not.toBeNull();
    const login = new URL(location!);
    expect(login.origin).toBe("https://pdi.invalid");
    expect(login.pathname).toBe("/login");
    expect(login.searchParams.get("next")).toBe("/documents/document-id");
  });

  it("allows an authenticated session to continue to the protected route", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/search", {
      headers: { cookie: "pdi_session=synthetic-session" },
    }));

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects an unauthenticated fresh installation to setup", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ setup_required: true }), { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/login"));
    expect(new URL(response.headers.get("location")!).pathname).toBe("/setup");
  });

  it("redirects stale setup navigation after setup completes", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ setup_required: false }), { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/setup"));
    expect(new URL(response.headers.get("location")!).pathname).toBe("/login");
  });

  it("never reopens setup for an authenticated installation", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/setup", {
      headers: { cookie: "pdi_session=synthetic-session" },
    }));
    expect(new URL(response.headers.get("location")!).pathname).toBe("/");
  });

  it("ignores a stale session cookie when a fresh database requires setup", async () => {
    vi.stubEnv("PDI_AUTH_ENABLED", "true");
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ setup_required: true }), { status: 200 })));
    const response = await proxy(new NextRequest("https://pdi.invalid/documents", {
      headers: { cookie: "pdi_session=stale-session" },
    }));

    expect(new URL(response.headers.get("location")!).pathname).toBe("/setup");
  });
});
