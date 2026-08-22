import { ArrowRight, CalendarClock, FileCheck2, Files, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { getDocuments, getKnowledgeReview, getReviewQueue } from "@/lib/api/server";

export default async function OverviewPage() {
  const [documents, review, knowledge] = await Promise.all([
    getDocuments().catch(() => ({ items: [], total: 0, limit: 50, offset: 0 })),
    getReviewQueue().catch(() => ({ items: [], total: 0, limit: 50, offset: 0 })),
    getKnowledgeReview().catch(() => ({ items: [], total: 0, limit: 50, offset: 0 })),
  ]);
  const recent = documents.items.slice(0, 4);
  return <div className="page">
    <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><p className="eyebrow">Private document intelligence</p><h1 className="mt-2 max-w-2xl text-3xl font-semibold tracking-[-0.04em] text-stone-950 sm:text-4xl">Your archive, ready when you need it.</h1><p className="page-description">Search source text, review proposed facts, and follow confirmed obligations from one local-first system.</p></div><Link href="/search" className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-[#274c3b] px-4 text-sm font-medium text-white shadow-sm hover:bg-[#1f3d30]"><Search className="size-4" />Search PDI</Link></div>
    <div className="mt-8 grid gap-3 sm:grid-cols-3">
      <Metric href="/documents" icon={Files} label="Documents" value={documents.total} note="Private source files" />
      <Metric href="/review" icon={FileCheck2} label="Document review" value={review.total} note="Documents awaiting confirmation" tone={review.total ? "attention" : "calm"} />
      <Metric href="/review/knowledge" icon={ShieldCheck} label="Knowledge review" value={knowledge.total} note="Evidence-backed proposals" tone={knowledge.total ? "attention" : "calm"} />
    </div>
    <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="panel overflow-hidden"><div className="flex items-center justify-between border-b border-stone-100 px-5 py-4"><div><h2 className="text-sm font-semibold text-stone-900">Recent documents</h2><p className="mt-0.5 text-xs text-stone-400">Latest additions to the archive</p></div><Link href="/documents" className="text-xs font-medium text-emerald-800">View all →</Link></div>{recent.length ? <div className="divide-y divide-stone-100">{recent.map((item) => <Link key={item.id} href={`/documents/${item.id}`} className="flex min-w-0 items-center justify-between gap-4 px-5 py-3.5 hover:bg-stone-50"><div className="min-w-0"><p className="truncate text-sm font-medium text-stone-800" title={item.title}>{item.title}</p><p className="mt-0.5 truncate text-xs text-stone-400">{item.original_filename}</p></div><span className="status-pill shrink-0 border-stone-200 bg-stone-50 text-stone-500">{item.status.replaceAll("_", " ")}</span></Link>)}</div> : <div className="px-5 py-12 text-center text-sm text-stone-400">No documents yet.</div>}</section>
      <aside className="panel p-5"><CalendarClock className="size-5 text-emerald-800" /><h2 className="mt-5 text-sm font-semibold text-stone-900">Confirmed obligations</h2><p className="mt-2 text-sm leading-6 text-stone-500">Upcoming contains only reviewed deadlines and explicit action items—not predictions or recommendations.</p><Link href="/upcoming" className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-emerald-800">Open Upcoming <ArrowRight className="size-4" /></Link></aside>
    </div>
  </div>;
}

function Metric({ href, icon: Icon, label, value, note, tone = "plain" }: { href: string; icon: typeof Files; label: string; value: number; note: string; tone?: "plain" | "attention" | "calm" }) {
  return <Link href={href} className="panel group p-5 transition hover:-translate-y-0.5 hover:shadow-md"><div className="flex items-start justify-between"><span className={`grid size-9 place-items-center rounded-lg ${tone === "attention" ? "bg-amber-50 text-amber-700" : tone === "calm" ? "bg-emerald-50 text-emerald-700" : "bg-stone-100 text-stone-600"}`}><Icon className="size-4" /></span><ArrowRight className="size-4 text-stone-300 transition group-hover:translate-x-0.5 group-hover:text-stone-500" /></div><p className="mt-5 text-2xl font-semibold tracking-tight text-stone-950">{value.toLocaleString("de-DE")}</p><p className="mt-1 text-sm font-medium text-stone-700">{label}</p><p className="mt-0.5 text-xs text-stone-400">{note}</p></Link>;
}
