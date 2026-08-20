import { Bot, Clock3, FileCheck2, FileSearch, FileText, LayoutDashboard, Lightbulb, Settings } from "lucide-react";
import Link from "next/link";

const navigation = [
  { label: "Overview", icon: LayoutDashboard, href: "/", enabled: true },
  { label: "Documents", icon: FileText, href: "/documents", enabled: true },
  { label: "Search", icon: FileSearch, href: "/search", enabled: true },
  { label: "Review", icon: FileCheck2, href: "/review", enabled: true },
  { label: "Timeline", icon: Clock3, href: "#", enabled: false },
  { label: "Insights", icon: Lightbulb, href: "#", enabled: false },
  { label: "Ask PDI", icon: Bot, href: "#", enabled: false },
  { label: "Settings", icon: Settings, href: "#", enabled: false },
];

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 border-r border-stone-200/80 bg-[#f6f4ef] px-4 py-5 md:flex md:flex-col">
      <Link href="/" className="mb-8 flex items-center gap-2.5 px-2 text-stone-900">
        <span className="grid size-8 place-items-center rounded-[10px] bg-stone-900 text-sm font-semibold text-white">P</span>
        <span className="font-semibold tracking-tight">Private Document Intelligence</span>
      </Link>
      <nav className="space-y-1" aria-label="Primary navigation">
        {navigation.map(({ label, icon: Icon, href, enabled }) => (
          <Link
            key={label}
            href={href}
            aria-disabled={!enabled}
            tabIndex={enabled ? undefined : -1}
            className={`group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition ${
              enabled ? "text-stone-700 hover:bg-white/70 hover:text-stone-950" : "cursor-default text-stone-400"
            }`}
          >
            <Icon className="size-4" strokeWidth={1.8} />
            <span>{label}</span>
            {!enabled && <span className="ml-auto text-[10px] uppercase tracking-wider text-stone-400">Soon</span>}
          </Link>
        ))}
      </nav>
      <div className="mt-auto rounded-xl border border-stone-200/80 bg-white/55 p-3 text-xs leading-5 text-stone-500">
        Your documents stay on infrastructure you control.
      </div>
    </aside>
  );
}
