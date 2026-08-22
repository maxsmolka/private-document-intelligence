import Link from "next/link";
import { CalendarClock, CheckSquare2 } from "lucide-react";
import { KnowledgeShell, dateLabel, label } from "@/components/knowledge-shell";
import { getActionItems, getDeadlines, getKnowledgeReview } from "@/lib/api/server";

export const metadata = { title: "Upcoming" };
export default async function UpcomingPage() {
  const [deadlines, actions, pendingDeadlines, pendingActions] = await Promise.all([getDeadlines(), getActionItems(), getKnowledgeReview("deadline"), getKnowledgeReview("action_item")]);
  const pending = pendingDeadlines.total + pendingActions.total;
  const empty = !deadlines.items.length && !actions.items.length;
  return <KnowledgeShell eyebrow="Obligations" title="Upcoming" description="Confirmed deadlines and explicit document-backed actions. Suggestions stay in review until you accept them.">
    {empty ? <div className="empty-state mb-8"><div><CalendarClock className="mx-auto size-8 text-stone-300" /><p className="mt-3 text-sm font-medium text-stone-700">No confirmed upcoming obligations</p><p className="mt-1 text-xs text-stone-400">PDI will show only obligations you have reviewed.</p>{pending ? <Link href="/review/knowledge" className="mt-4 inline-block text-sm font-medium text-emerald-800">Review suggestions ({pending}) →</Link> : null}</div></div> : null}
    <div className="grid gap-7 lg:grid-cols-2">
      <ObligationSection icon={CalendarClock} title="Deadlines" empty="No confirmed open deadlines.">{deadlines.items.map((item) => { const evidence = item.evidence[0]; return <Link key={item.id} href={`/documents/${item.source_document_id}${evidence ? `?page=${evidence.page}` : ""}`} className="block p-4 hover:bg-stone-50"><div className="flex justify-between gap-4"><div className="min-w-0"><p className="break-words text-sm font-medium text-stone-800">{item.title}</p><p className="mt-1 text-xs text-stone-400">{label(item.deadline_type)}{item.original_rule ? ` · ${item.original_rule}` : ""}</p></div><time className="shrink-0 text-xs font-semibold tabular-nums text-stone-600">{dateLabel(item.due_at)}</time></div><p className="mt-2 text-[11px] font-medium text-emerald-800">Open source{evidence ? ` · page ${evidence.page}` : ""} →</p></Link>; })}</ObligationSection>
      <ObligationSection icon={CheckSquare2} title="Action items" empty="No confirmed open action items.">{actions.items.map((item) => { const evidence = item.evidence[0]; return <Link key={item.id} href={`/documents/${item.source_document_id}${evidence ? `?page=${evidence.page}` : ""}`} className="block p-4 hover:bg-stone-50"><div className="flex justify-between gap-4"><div className="min-w-0"><p className="break-words text-sm font-medium text-stone-800">{item.title}</p><p className="mt-1 text-xs text-stone-400">{label(item.life_area)} · {label(item.priority)} priority</p></div><time className="shrink-0 text-xs font-semibold tabular-nums text-stone-600">{dateLabel(item.due_at)}</time></div><p className="mt-2 text-[11px] font-medium text-emerald-800">Open source{evidence ? ` · page ${evidence.page}` : ""} →</p></Link>; })}</ObligationSection>
    </div>
  </KnowledgeShell>;
}

function ObligationSection({ icon: Icon, title, empty, children }: { icon: typeof CalendarClock; title: string; empty: string; children: React.ReactNode }) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return <section><div className="mb-3 flex items-center gap-2"><span className="grid size-8 place-items-center rounded-lg bg-emerald-50 text-emerald-800"><Icon className="size-4" /></span><h2 className="text-sm font-semibold text-stone-900">{title}</h2></div><div className="panel divide-y divide-stone-100 overflow-hidden">{hasChildren ? children : <p className="p-8 text-center text-sm text-stone-400">{empty}</p>}</div></section>;
}
