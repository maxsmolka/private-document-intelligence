import { BookOpenText } from "lucide-react";

export function KnowledgeShell({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: React.ReactNode }) {
  return <div className="mx-auto max-w-6xl px-5 py-8 md:px-8 md:py-10"><div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-stone-400"><BookOpenText className="size-4" />{eyebrow}</div><h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em] text-stone-950">{title}</h1><p className="mt-1 max-w-2xl text-sm text-stone-500">{description}</p><div className="mt-7">{children}</div></div>;
}

export const label = (value: string) => value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
export const dateLabel = (value: string | null) => value ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(`${value}T00:00:00`)) : "Date unresolved";
