import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const routeState = vi.hoisted(() => ({ pathname: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => routeState.pathname,
}));

import { Sidebar } from "@/components/sidebar";

afterEach(cleanup);

describe("Sidebar active navigation", () => {
  it.each([
    ["/", "Overview"],
    ["/documents", "Documents"],
    ["/documents/document-id", "Documents"],
    ["/search", "Search PDI"],
    ["/review", "Document review"],
    ["/review/document-id", "Document review"],
    ["/review/knowledge", "Knowledge review"],
    ["/review/knowledge/proposal-id", "Knowledge review"],
    ["/organizations", "Organizations"],
    ["/organizations/organization-id", "Organizations"],
    ["/contracts", "Contracts"],
    ["/contracts/contract-id", "Contracts"],
    ["/timeline", "Timeline"],
    ["/upcoming", "Upcoming"],
    ["/settings/account", "Account"],
    ["/settings/administration", "Administration"],
    ["/settings/security", "Security"],
    ["/settings/sessions", "Sessions"],
    ["/settings/tokens", "API Tokens"],
    ["/settings/ingestion", "Ingestion"],
    ["/settings/ingestion/source/source-id", "Ingestion"],
    ["/settings/about", "About"],
    ["/admin/users", "Users"],
  ])("marks only the owner of %s active", (route, label) => {
    routeState.pathname = route;
    const { container } = render(<Sidebar open onClose={() => undefined} />);
    const activeItems = container.querySelectorAll('[aria-current="page"]');
    expect(activeItems).toHaveLength(1);
    expect(screen.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  });
});
