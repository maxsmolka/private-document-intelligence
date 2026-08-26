import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/api/pdi/[...path]/route";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("PDI proxy build metadata", () => {
  it("overwrites untrusted client metadata with the running web build", async () => {
    vi.stubEnv("PDI_WEB_VERSION", "1.1.2");
    vi.stubEnv("PDI_WEB_REVISION", "trusted-revision");
    vi.stubEnv("PDI_WEB_BUILD_TIME", "2026-08-26T00:00:00Z");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await GET(
      new NextRequest("https://pdi.invalid/api/pdi/api/v1/system/info", {
        headers: { "x-pdi-web-version": "attacker-value", cookie: "pdi_session=test", origin: "https://pdi.invalid" },
      }),
      { params: Promise.resolve({ path: ["api", "v1", "system", "info"] }) },
    );
    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("x-pdi-web-version")).toBe("1.1.2");
    expect(headers.get("x-pdi-web-revision")).toBe("trusted-revision");
    expect(headers.get("x-pdi-web-build-time")).toBe("2026-08-26T00:00:00Z");
    expect(headers.get("origin")).toBe("https://pdi.invalid");
  });
});
