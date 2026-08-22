"use client";

import { FileImage, FileText, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import type { DocumentRecord } from "@/lib/api/documents";

const statuses = ["inbox", "processing", "ready", "needs_review", "archived", "failed"];
const areas = ["finance", "insurance", "vehicle", "home", "health", "tax", "work", "travel", "personal", "other"];

function label(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function fileSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`; }

export function DocumentExplorer({ documents }: { documents: DocumentRecord[] }) {
  const router = useRouter(); const pathname = usePathname(); const params = useSearchParams();
  const [search, setSearch] = useState("");
  const visible = useMemo(() => documents.filter((document) => `${document.title} ${document.original_filename}`.toLowerCase().includes(search.toLowerCase())), [documents, search]);

  function filter(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value); else next.delete(key);
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`);
  }

  return (
    <>
      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Filter documents by title or filename</span><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter documents" className="field pl-9" /></label>
        <select aria-label="Filter by status" value={params.get("status") ?? ""} onChange={(event) => filter("status", event.target.value)} className="field sm:w-44"><option value="">All statuses</option>{statuses.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select>
        <select aria-label="Filter by life area" value={params.get("life_area") ?? ""} onChange={(event) => filter("life_area", event.target.value)} className="field sm:w-44"><option value="">All life areas</option>{areas.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select>
      </div>
      {visible.length === 0 ? <div className="empty-state mt-5"><div><FileText className="mx-auto size-8 text-stone-300" /><h2 className="mt-4 text-sm font-medium text-stone-700">No documents found</h2><p className="mt-1 text-sm text-stone-400">Add a document or adjust your filters.</p></div></div> : <div className="panel mt-5 overflow-hidden"><div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(100px,.8fr)_minmax(100px,.8fr)_120px_100px] gap-4 border-b border-stone-200 bg-stone-50/80 px-5 py-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-stone-400 md:grid"><span>Document</span><span>Type</span><span>Life area</span><span>Date</span><span>Status</span></div><div className="divide-y divide-stone-100">{visible.map((document) => {
        const Icon = document.mime_type.startsWith("image/") ? FileImage : FileText;
        const date = document.document_date ? new Date(`${document.document_date}T00:00:00Z`) : new Date(document.created_at);
        return <Link key={document.id} href={`/documents/${document.id}`} className="group grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-3 px-4 py-4 transition hover:bg-stone-50/80 md:grid-cols-[minmax(0,2.2fr)_minmax(100px,.8fr)_minmax(100px,.8fr)_120px_100px] md:gap-4 md:px-5"><div className="flex min-w-0 items-center gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-stone-100 text-stone-500"><Icon className="size-4" /></span><div className="min-w-0"><p className="truncate text-sm font-medium text-stone-900" title={document.title}>{document.title}</p><p className="mt-0.5 truncate text-xs text-stone-400" title={document.original_filename}>{document.original_filename} · {fileSize(document.file_size)}</p></div></div><p className="hidden truncate text-sm text-stone-500 md:block">{document.document_type ? label(document.document_type) : "—"}</p><p className="hidden text-sm text-stone-500 md:block">{label(document.life_area)}</p><p className="hidden text-sm tabular-nums text-stone-500 md:block">{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeZone: "UTC" }).format(date)}</p><div className="flex items-center justify-between gap-2 md:block"><span className="text-xs text-stone-400 md:hidden">{label(document.life_area)} · {new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeZone: "UTC" }).format(date)}</span><span className="status-pill border-stone-200 bg-white text-stone-600">{label(document.status)}</span></div></Link>;
      })}</div></div>}
    </>
  );
}
