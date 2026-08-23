import { describe, expect, it } from "vitest";
import { activeNavigationRoute } from "@/lib/navigation";

describe("activeNavigationRoute", () => {
  it.each([
    ["overview", "/", "/"],
    ["documents", "/documents", "/documents"],
    ["document detail", "/documents/6eb3d86a", "/documents"],
    ["search", "/search", "/search"],
    ["document review", "/review", "/review"],
    ["document review selection", "/review/6eb3d86a", "/review"],
    ["knowledge review", "/review/knowledge", "/review/knowledge"],
    ["knowledge review nested", "/review/knowledge/proposal", "/review/knowledge"],
    ["organizations", "/organizations", "/organizations"],
    ["organization detail", "/organizations/6eb3d86a", "/organizations"],
    ["contracts", "/contracts", "/contracts"],
    ["contract detail", "/contracts/6eb3d86a", "/contracts"],
    ["timeline", "/timeline", "/timeline"],
    ["upcoming", "/upcoming", "/upcoming"],
  ])("owns the %s route", (_label, pathname, expected) => {
    expect(activeNavigationRoute(pathname)).toBe(expected);
  });

  it("does not assign an unrelated or partial-prefix route", () => {
    expect(activeNavigationRoute("/reviewer")).toBeNull();
    expect(activeNavigationRoute("/unknown")).toBeNull();
  });
});
