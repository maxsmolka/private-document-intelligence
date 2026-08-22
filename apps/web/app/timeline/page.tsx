import Link from "next/link";
import { CalendarRange } from "lucide-react";
import { KnowledgeShell, dateLabel, label } from "@/components/knowledge-shell";
import { getKnowledgeReview, getTimeline } from "@/lib/api/server";
import type { TimelineEvent } from "@/lib/api/knowledge";

interface Filters { life_area?: string; event_type?: string; date_from?: string; date_to?: string }
export const metadata = { title: "Timeline" };

export default async function TimelinePage({ searchParams }: { searchParams: Promise<Filters> }) {
  const filters = await searchParams;
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const [data, pending] = await Promise.all([getTimeline(params), getKnowledgeReview("event")]);
  const eventTypes = ["document_received", "contract_started", "contract_changed", "contract_renewed", "contract_cancelled", "contract_ended", "payment_due", "invoice_issued", "policy_changed", "tariff_changed", "deadline_set", "official_decision", "other"];
  const groups = data.items.reduce<Record<string, TimelineEvent[]>>((result, item) => {
    const key = item.event_date ? new Intl.DateTimeFormat("en", { year: "numeric", month: "long", timeZone: "UTC" }).format(new Date(`${item.event_date}T00:00:00Z`)) : "Date unresolved";
    (result[key] ??= []).push(item);
    return result;
  }, {});
  const year = new Date().getUTCFullYear();
  return <KnowledgeShell eyebrow="Life model" title="Timeline" description="Confirmed events in source chronology. Upload activity and unreviewed suggestions do not appear here.">
    <div className="mb-4 flex flex-wrap gap-2 text-xs"><Link href="/timeline" className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-stone-600">All time</Link><Link href={`/timeline?date_from=${year}-01-01&date_to=${year}-12-31`} className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-stone-600">This year</Link><Link href={`/timeline?date_from=${year - 1}-01-01&date_to=${year - 1}-12-31`} className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-stone-600">Last year</Link></div>
    <form className="panel mb-7 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
      <Filter label="Life area"><select name="life_area" defaultValue={filters.life_area ?? ""} className="field"><option value="">All life areas</option>{["insurance", "finance", "vehicle", "home", "health", "tax", "work", "travel", "personal", "other"].map((area) => <option key={area} value={area}>{label(area)}</option>)}</select></Filter>
      <Filter label="Event type"><select name="event_type" defaultValue={filters.event_type ?? ""} className="field"><option value="">All event types</option>{eventTypes.map((type) => <option key={type} value={type}>{label(type)}</option>)}</select></Filter>
      <Filter label="From"><input name="date_from" type="date" defaultValue={filters.date_from ?? ""} className="field" /></Filter>
      <Filter label="To"><input name="date_to" type="date" defaultValue={filters.date_to ?? ""} className="field" /></Filter>
      <button className="h-10 self-end rounded-lg bg-stone-900 px-3 text-sm font-medium text-white">Apply filters</button>
    </form>
    {data.items.length ? <div className="space-y-8">{Object.entries(groups).map(([month, items]) => <section key={month}><div className="mb-3 flex items-center gap-2"><CalendarRange className="size-4 text-emerald-800" /><h2 className="text-sm font-semibold text-stone-800">{month}</h2><span className="text-xs text-stone-400">{items.length}</span></div><ol className="panel divide-y divide-stone-100 overflow-hidden">{items.map((item) => <li key={item.id} className="grid gap-3 p-5 sm:grid-cols-[120px_minmax(0,1fr)]"><time className="text-xs font-semibold tabular-nums text-stone-500">{dateLabel(item.event_date)}</time><div className="min-w-0"><h3 className="break-words text-sm font-medium text-stone-900">{item.title}</h3><p className="mt-1 text-xs text-stone-400">{label(item.life_area)} · {label(item.event_type)} · {label(item.event_date_precision)} date</p>{item.evidence[0] ? <blockquote className="mt-3 border-l-2 border-amber-200 pl-3 text-sm text-stone-600">“{item.evidence[0].text}” <Link href={`/documents/${item.source_document_id}?page=${item.evidence[0].page}`} className="text-xs font-medium text-emerald-800">Page {item.evidence[0].page} · Show in document →</Link></blockquote> : null}</div></li>)}</ol></section>)}</div> : <div className="empty-state"><div><p className="text-sm font-medium text-stone-600">No confirmed document-backed events match these filters.</p>{pending.total ? <Link href="/review/knowledge" className="mt-3 inline-block text-sm font-medium text-emerald-800">Review event suggestions ({pending.total}) →</Link> : null}</div></div>}
  </KnowledgeShell>;
}

function Filter({ label: name, children }: { label: string; children: React.ReactNode }) { return <label><span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-stone-400">{name}</span>{children}</label>; }
