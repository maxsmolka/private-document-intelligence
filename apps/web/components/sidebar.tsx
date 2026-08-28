"use client";

import { Building2, CalendarClock, Clock3, FileCheck2, FileSearch, FileText, Inbox, Info, KeyRound, LayoutDashboard, Lightbulb, MonitorSmartphone, RefreshCw, ScrollText, Settings, ShieldCheck, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { activeNavigationRoute } from "@/lib/navigation";

const groups = [
  { label: "Library", items: [
    { label: "Overview", icon: LayoutDashboard, href: "/" },
    { label: "Documents", icon: FileText, href: "/documents" },
    { label: "Search PDI", icon: FileSearch, href: "/search" },
    { label: "Document review", icon: FileCheck2, href: "/review" },
  ] },
  { label: "Knowledge", items: [
    { label: "Knowledge review", icon: Lightbulb, href: "/review/knowledge" },
    { label: "Organizations", icon: Building2, href: "/organizations" },
    { label: "Contracts", icon: ScrollText, href: "/contracts" },
    { label: "Timeline", icon: Clock3, href: "/timeline" },
    { label: "Upcoming", icon: CalendarClock, href: "/upcoming" },
  ] },
  { label: "Settings", items: [
    { label: "Account", icon: Settings, href: "/settings/account" },
    { label: "Security", icon: ShieldCheck, href: "/settings/security" },
    { label: "Sessions", icon: MonitorSmartphone, href: "/settings/sessions" },
    { label: "API Tokens", icon: KeyRound, href: "/settings/tokens" },
    { label: "Ingestion", icon: Inbox, href: "/settings/ingestion" },
    { label: "Updates", icon: RefreshCw, href: "/settings/updates" },
    { label: "About", icon: Info, href: "/settings/about" },
    { label: "Users", icon: Users, href: "/admin/users" },
  ] },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const activeRoute = activeNavigationRoute(pathname);
  return (
    <>
      {open ? <button type="button" aria-label="Close navigation" onClick={onClose} className="fixed inset-0 z-40 bg-stone-950/30 backdrop-blur-[2px] md:hidden" /> : null}
      <aside className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col overflow-y-auto border-r border-stone-200 bg-[#f1f1ee] px-3 py-4 transition-transform duration-200 md:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex items-center">
          <Link href="/" onClick={onClose} className="flex min-w-0 items-center gap-3 px-2 text-stone-900">
            <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-[#274c3b] text-sm font-semibold text-white shadow-sm">P</span>
            <span className="min-w-0"><span className="block text-sm font-semibold tracking-tight">PDI</span><span className="block truncate text-[11px] text-stone-500">Private Document Intelligence</span></span>
          </Link>
          <button type="button" onClick={onClose} className="ml-auto rounded-lg p-2 text-stone-500 hover:bg-white md:hidden" aria-label="Close navigation"><X className="size-4" /></button>
        </div>
        <nav className="mt-7 space-y-6" aria-label="Primary navigation">
          {groups.map((group) => <div key={group.label}>
            <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-stone-400">{group.label}</p>
            <div className="mt-1.5 space-y-0.5">{group.items.map(({ label, icon: Icon, href }) => {
              const active = activeRoute === href;
              return <Link key={label} href={href} onClick={onClose} aria-current={active ? "page" : undefined} className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition ${active ? "bg-white text-stone-950 shadow-sm" : "text-stone-600 hover:bg-white/60 hover:text-stone-950"}`}><Icon className={`size-4 ${active ? "text-emerald-800" : "text-stone-400"}`} strokeWidth={1.8} /><span>{label}</span></Link>;
            })}</div>
          </div>)}
        </nav>
        <div className="mt-auto rounded-xl border border-stone-200 bg-white/65 p-3 text-[11px] leading-5 text-stone-500">
          Local-first. Private by design.<br />Your source files remain unchanged.
        </div>
      </aside>
    </>
  );
}
