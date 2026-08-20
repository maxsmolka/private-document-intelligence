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
      <div className="flex flex-col gap-3 border-b border-stone-200 py-4 sm:flex-row">
        <label className="relative flex-1"><span className="sr-only">Search documents</span><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-400" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search documents…" className="h-9 w-full rounded-lg border border-stone-200 bg-white pl-9 pr-3 text-sm outline-none transition placeholder:text-stone-400 focus:border-stone-400 focus:ring-2 focus:ring-stone-100" /></label>
        <select aria-label="Filter by status" value={params.get("status") ?? ""} onChange={(event) => filter("status", event.target.value)} className="h-9 rounded-lg border border-stone-200 bg-white px-3 text-sm text-stone-600 outline-none focus:border-stone-400"><option value="">All statuses</option>{statuses.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select>
        <select aria-label="Filter by life area" value={params.get("life_area") ?? ""} onChange={(event) => filter("life_area", event.target.value)} className="h-9 rounded-lg border border-stone-200 bg-white px-3 text-sm text-stone-600 outline-none focus:border-stone-400"><option value="">All life areas</option>{areas.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select>
      </div>
      {visible.length === 0 ? <div className="py-24 text-center"><FileText className="mx-auto size-8 text-stone-300" /><h2 className="mt-4 text-sm font-medium text-stone-700">No documents found</h2><p className="mt-1 text-sm text-stone-400">Add a document or adjust your filters.</p></div> : <div className="divide-y divide-stone-200/80">{visible.map((document) => {
        const Icon = document.mime_type.startsWith("image/") ? FileImage : FileText;
        return <Link key={document.id} href={`/documents/${document.id}`} className="group grid grid-cols-[auto_1fr] items-center gap-4 py-4 transition hover:bg-white/50 sm:grid-cols-[auto_minmax(0,2fr)_1fr_1fr_auto] sm:px-2"><span className="grid size-10 place-items-center rounded-xl border border-stone-200 bg-white text-stone-500 shadow-sm"><Icon className="size-4" /></span><div className="min-w-0"><p className="truncate text-sm font-medium text-stone-800 group-hover:text-stone-950">{document.title}</p><p className="mt-1 truncate text-xs text-stone-400">{document.original_filename} · {fileSize(document.file_size)}</p></div><p className="hidden text-sm capitalize text-stone-500 sm:block">{label(document.life_area)}</p><p className="hidden text-sm text-stone-500 sm:block">{document.document_date ? new Date(document.document_date).toLocaleDateString() : new Date(document.created_at).toLocaleDateString()}</p><span className="hidden rounded-full border border-stone-200 bg-white px-2.5 py-1 text-[11px] font-medium capitalize text-stone-500 sm:inline">{label(document.status)}</span></Link>;
      })}</div>}
    </>
  );
}

