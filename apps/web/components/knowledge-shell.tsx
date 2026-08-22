import { BookOpenText } from "lucide-react";

export function KnowledgeShell({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: React.ReactNode }) {
  return <div className="page"><div className="eyebrow flex items-center gap-2"><BookOpenText className="size-4 text-emerald-800" />{eyebrow}</div><h1 className="page-title mt-2 break-words">{title}</h1><p className="page-description">{description}</p><div className="mt-7">{children}</div></div>;
}

export const label = (value: string) => value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
export const dateLabel = (value: string | null) => value ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(`${value}T00:00:00`)) : "Date unresolved";
