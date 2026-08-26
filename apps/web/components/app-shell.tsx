"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const pathname = usePathname();

  if (pathname === "/login" || pathname === "/setup") return <main>{children}</main>;

  return (
    <div className="min-h-dvh">
      <Sidebar open={navigationOpen} onClose={() => setNavigationOpen(false)} />
      <div className="min-w-0 md:pl-64">
        <Topbar onOpenNavigation={() => setNavigationOpen(true)} />
        <main>{children}</main>
      </div>
    </div>
  );
}
