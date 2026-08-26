import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";

const usePathname = vi.fn();

vi.mock("next/navigation", () => ({ usePathname: () => usePathname() }));
vi.mock("@/components/sidebar", () => ({ Sidebar: () => <aside>Application navigation</aside> }));
vi.mock("@/components/topbar", () => ({ Topbar: () => <header>Application toolbar</header> }));

describe("AppShell", () => {
  beforeEach(() => usePathname.mockReset());
  afterEach(cleanup);

  it.each(["/login", "/setup"])("renders %s without the authenticated shell", (pathname) => {
    usePathname.mockReturnValue(pathname);
    render(<AppShell><p>Public content</p></AppShell>);

    expect(screen.getByText("Public content")).toBeInTheDocument();
    expect(screen.queryByText("Application navigation")).not.toBeInTheDocument();
    expect(screen.queryByText("Application toolbar")).not.toBeInTheDocument();
  });

  it("renders normal application routes inside the authenticated shell", () => {
    usePathname.mockReturnValue("/documents");
    render(<AppShell><p>Private content</p></AppShell>);

    expect(screen.getByText("Application navigation")).toBeInTheDocument();
    expect(screen.getByText("Application toolbar")).toBeInTheDocument();
    expect(screen.getByText("Private content")).toBeInTheDocument();
  });
});
