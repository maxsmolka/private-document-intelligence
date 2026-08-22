"use client";

import { ArrowLeft, ArrowRight, FileSearch, Search, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import type { LifeArea, SearchResponse, SearchSnippet } from "@/lib/api/documents";

const areas: LifeArea[] = ["finance", "insurance", "vehicle", "home", "health", "tax", "work", "travel", "personal", "other"];
const statuses = ["ready", "needs_review", "inbox", "processing", "archived", "failed"];
const label = (value: string) => value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

interface Filters { q?: string; offset?: string; status?: string; life_area?: string; document_type?: string; date_from?: string; date_to?: string }

export function SearchWorkspace({ data, filters, unavailable }: { data: SearchResponse; filters: Filters; unavailable: boolean }) {
  const router = useRouter();
  const [query, setQuery] = useState(filters.q ?? "");
  const [advanced, setAdvanced] = useState(Boolean(filters.status || filters.life_area || filters.document_type || filters.date_from || filters.date_to));
  const [active, setActive] = useState(-1);
  const form = useRef<HTMLFormElement>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    const values = new FormData(form.current ?? undefined);
    const params = new URLSearchParams();
    for (const [key, value] of values.entries()) if (String(value).trim()) params.set(key, String(value).trim());
    router.push(`/search?${params}`);
  }
  function navigate(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (event.key === "ArrowDown" || event.key.toLowerCase() === "j") { event.preventDefault(); setActive((value) => Math.min(data.results.length - 1, value + 1)); }
    if (event.key === "ArrowUp" || event.key.toLowerCase() === "k") { event.preventDefault(); setActive((value) => Math.max(0, value - 1)); }
    if (event.key === "Enter" && active >= 0) router.push(`/documents/${data.results[active].document_id}`);
  }
  const hasFilters = Boolean(filters.status || filters.life_area || filters.document_type || filters.date_from || filters.date_to);
  return <div className="page-narrow" onKeyDown={navigate} tabIndex={-1}>
    <div><div className="eyebrow flex items-center gap-2"><FileSearch className="size-4" />Retrieval</div><h1 className="page-title mt-2">Search PDI</h1><p className="page-description">Search confirmed metadata and extracted source text. Every result stays grounded in a document.</p></div>
    <form ref={form} onSubmit={submit} className="mt-7 border-b border-stone-200 pb-6">
      <div className="flex gap-2"><label className="relative flex-1"><span className="sr-only">Search query</span><Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-stone-400" /><input name="q" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={200} autoComplete="off" placeholder="Organization, identifier, amount, or document text" className="h-11 w-full rounded-xl border border-stone-300 bg-white pl-10 pr-10 text-sm outline-none transition focus:border-stone-500 focus:ring-4 focus:ring-stone-100" />{query ? <button type="button" onClick={() => setQuery("")} aria-label="Clear query" className="absolute right-3 top-1/2 -translate-y-1/2 text-stone-400 hover:text-stone-700"><X className="size-4" /></button> : null}</label><button className="h-11 rounded-xl bg-stone-900 px-5 text-sm font-medium text-white hover:bg-stone-800">Search</button><button type="button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)} className="grid size-11 place-items-center rounded-xl border border-stone-200 bg-white text-stone-500 hover:text-stone-800" aria-label="Toggle search filters"><SlidersHorizontal className="size-4" /></button></div>
      {advanced ? <div className="mt-3 grid gap-3 rounded-xl bg-stone-100/70 p-3 sm:grid-cols-2 lg:grid-cols-5"><Filter label="Status"><select name="status" defaultValue={filters.status ?? ""} className="field"><option value="">Any status</option>{statuses.map((status) => <option key={status} value={status}>{label(status)}</option>)}</select></Filter><Filter label="Life area"><select name="life_area" defaultValue={filters.life_area ?? ""} className="field"><option value="">Any area</option>{areas.map((area) => <option key={area} value={area}>{label(area)}</option>)}</select></Filter><Filter label="Document type"><input name="document_type" defaultValue={filters.document_type ?? ""} maxLength={100} className="field" placeholder="e.g. invoice" /></Filter><Filter label="From"><input name="date_from" type="date" defaultValue={filters.date_from ?? ""} className="field" /></Filter><Filter label="To"><input name="date_to" type="date" defaultValue={filters.date_to ?? ""} className="field" /></Filter></div> : null}
    </form>
    {unavailable ? <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Search is temporarily unavailable. Your documents are unaffected.</div> : data.query || hasFilters ? <section className="mt-6" aria-live="polite"><div className="flex items-center justify-between text-xs text-stone-500"><span>{data.total} {data.total === 1 ? "result" : "results"}{data.query ? <> for <strong className="font-medium text-stone-700">“{data.query}”</strong></> : null}</span>{hasFilters ? <Link href={data.query ? `/search?q=${encodeURIComponent(data.query)}` : "/search"} className="text-stone-500 hover:text-stone-900">Reset filters</Link> : null}</div>{data.results.length ? <ol className="panel mt-3 divide-y divide-stone-100 overflow-hidden">{data.results.map((result, index) => <li key={result.document_id} className={`px-5 py-5 transition ${active === index ? "bg-emerald-50/60 ring-1 ring-inset ring-emerald-800/10" : "hover:bg-stone-50/70"}`}><div className="flex items-start justify-between gap-4"><div className="min-w-0"><Link href={`/documents/${result.document_id}`} className="font-medium text-stone-950 hover:text-emerald-900"><h2 className="truncate" title={result.title}>{result.title}</h2></Link><p className="mt-1 text-xs text-stone-500">{label(result.life_area)}{result.document_type ? ` · ${label(result.document_type)}` : ""}{result.document_date ? ` · ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(`${result.document_date}T00:00:00`))}` : ""}</p></div><span className="status-pill shrink-0 border-stone-200 bg-stone-50 text-stone-500">{label(result.status)}</span></div>{result.snippets.map((snippet) => <Snippet key={`${snippet.page}-${snippet.text}`} snippet={snippet} documentId={result.document_id} />)}<p className="mt-3 text-[11px] text-stone-400">Matched in {result.matched_fields.map(label).join(" · ")}</p></li>)}</ol> : <div className="empty-state mt-6"><div><FileSearch className="mx-auto size-8 text-stone-300" /><p className="mt-3 text-sm font-medium text-stone-700">No documents found{data.query ? ` for “${data.query}”` : ""}</p><p className="mt-1 text-xs text-stone-400">Try fewer terms or reset the filters.</p></div></div>}<Pagination data={data} filters={filters} /></section> : <div className="empty-state mt-10"><div className="text-sm text-stone-500"><Search className="mx-auto mb-3 size-7 text-stone-300" />Search titles, organizations, identifiers, metadata, and exact source text.<p className="mt-2 text-xs text-stone-400">Use J/K to move through results and Enter to open.</p></div></div>}
  </div>;
}

function Filter({ label: fieldLabel, children }: { label: string; children: React.ReactNode }) { return <label><span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-stone-400">{fieldLabel}</span>{children}</label>; }

function Snippet({ snippet, documentId }: { snippet: SearchSnippet; documentId: string }) {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  snippet.highlight_ranges.forEach((range, index) => { parts.push(snippet.text.slice(cursor, range.start)); parts.push(<mark key={index} className="rounded-sm bg-amber-100 px-0.5 text-inherit">{snippet.text.slice(range.start, range.end)}</mark>); cursor = range.end; });
  parts.push(snippet.text.slice(cursor));
  return <Link href={`/documents/${documentId}?page=${snippet.page}`} className="mt-3 block max-w-3xl rounded-lg bg-stone-50 px-3 py-2.5 text-sm leading-6 text-stone-600 hover:bg-stone-100" aria-label={`Show match on page ${snippet.page}`}><span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-emerald-800">Page {snippet.page}</span>…{parts}… <span className="whitespace-nowrap text-xs font-medium text-emerald-800">Show in document →</span></Link>;
}

function Pagination({ data, filters }: { data: SearchResponse; filters: Filters }) {
  if (data.total <= data.limit) return null;
  const href = (offset: number) => { const params = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value && key !== "offset") params.set(key, value); }); if (offset) params.set("offset", String(offset)); return `/search?${params}`; };
  return <nav aria-label="Search result pages" className="mt-5 flex justify-between"><Link aria-disabled={data.offset === 0} tabIndex={data.offset === 0 ? -1 : undefined} href={href(Math.max(0, data.offset - data.limit))} className={data.offset === 0 ? "pointer-events-none text-stone-300" : "text-stone-600 hover:text-stone-950"}><span className="inline-flex items-center gap-1 text-sm"><ArrowLeft className="size-4" />Previous</span></Link><Link aria-disabled={data.offset + data.limit >= data.total} tabIndex={data.offset + data.limit >= data.total ? -1 : undefined} href={href(data.offset + data.limit)} className={data.offset + data.limit >= data.total ? "pointer-events-none text-stone-300" : "text-stone-600 hover:text-stone-950"}><span className="inline-flex items-center gap-1 text-sm">Next<ArrowRight className="size-4" /></span></Link></nav>;
}
