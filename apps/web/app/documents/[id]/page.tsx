import { ArrowLeft, CalendarDays, Database, FileText, Hash } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, documentContentUrl, getDocument } from "@/lib/api/documents";

function label(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }
function fileSize(bytes: number) { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`; }

async function load(id: string) { try { return await getDocument(id); } catch (error) { if (error instanceof ApiError && error.status === 404) notFound(); throw error; } }

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params; const document = await load(id); return { title: document.title, description: `Private document: ${document.original_filename}` };
}

export default async function DocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; const document = await load(id); const contentUrl = documentContentUrl(document.id);
  const metadata = [
    [FileText, "Filename", document.original_filename],
    [Database, "File size", fileSize(document.file_size)],
    [CalendarDays, "Added", new Date(document.created_at).toLocaleString()],
    [Hash, "SHA-256", document.sha256],
  ] as const;
  return <div className="mx-auto max-w-7xl px-5 py-8 md:px-8"><Link href="/documents" className="inline-flex items-center gap-2 text-sm text-stone-500 transition hover:text-stone-900"><ArrowLeft className="size-4" />Documents</Link><div className="mt-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end"><div><h1 className="text-3xl font-semibold tracking-[-0.035em] text-stone-950">{document.title}</h1><p className="mt-2 text-sm text-stone-500">{document.original_filename}</p></div><div className="flex gap-2"><span className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600">{label(document.life_area)}</span><span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">{label(document.status)}</span></div></div><div className="mt-9 grid gap-6 lg:grid-cols-[minmax(260px,0.38fr)_minmax(0,1fr)]"><section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm shadow-stone-950/[0.02]"><h2 className="text-sm font-semibold text-stone-900">Document information</h2><dl className="mt-5 space-y-5">{metadata.map(([Icon, term, value]) => <div key={term} className="grid grid-cols-[20px_1fr] gap-3"><Icon className="mt-0.5 size-4 text-stone-400" /><div><dt className="text-xs text-stone-400">{term}</dt><dd className={`mt-1 text-sm text-stone-700 ${term === "SHA-256" ? "break-all font-mono text-[11px] leading-5" : ""}`}>{value}</dd></div></div>)}</dl></section><section className="min-h-[68vh] overflow-hidden rounded-2xl border border-stone-200 bg-stone-100 shadow-sm shadow-stone-950/[0.03]"><div className="flex h-11 items-center border-b border-stone-200 bg-white px-4 text-xs font-medium text-stone-500">File preview</div>{document.mime_type.startsWith("image/") ? <div className="grid min-h-[calc(68vh-2.75rem)] place-items-center p-5"><img src={contentUrl} alt={`Preview of ${document.title}`} className="max-h-[62vh] max-w-full rounded shadow-lg" /></div> : <iframe src={contentUrl} title={`Preview of ${document.title}`} className="h-[calc(68vh-2.75rem)] w-full border-0" />}</section></div></div>;
}

