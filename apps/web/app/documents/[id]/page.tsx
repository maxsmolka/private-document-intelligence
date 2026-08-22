import { ArrowLeft, CalendarDays, Database, FileText, Hash, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DocumentPreview } from "@/components/document-preview";
import { ExtractionReviewPanel } from "@/components/extraction-review-panel";
import { RetryProcessingButton } from "@/components/retry-processing-button";
import { ApiError } from "@/lib/api/documents";
import { getDocument, getExtractionHistory } from "@/lib/api/server";

function label(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function fileSize(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function load(id: string) {
  try {
    return await getDocument(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const document = await load(id);
  return {
    title: document.title,
    description: `Private document: ${document.original_filename}`,
  };
}

export default async function DocumentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ page?: string }>;
}) {
  const { id } = await params;
  const requestedPage = Number((await searchParams).page ?? "1");
  const initialPage = Number.isFinite(requestedPage) && requestedPage > 0 ? Math.floor(requestedPage) : 1;
  const [document, extractionHistory] = await Promise.all([load(id), getExtractionHistory(id)]);
  const metadata = [
    [FileText, "Filename", document.original_filename],
    [Database, "File size", fileSize(document.file_size)],
    [CalendarDays, "Added", new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Berlin" }).format(new Date(document.created_at))],
    [Hash, "SHA-256", document.sha256],
  ] as const;

  return (
    <div className="page">
      <Link
        href="/documents"
        className="inline-flex items-center gap-2 text-sm text-stone-500 transition hover:text-stone-900"
      >
        <ArrowLeft className="size-4" />
        Documents
      </Link>
      <div className="mt-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div className="min-w-0">
          <h1 className="line-clamp-2 break-words text-3xl font-semibold tracking-[-0.035em] text-stone-950" title={document.title}>
            {document.title}
          </h1>
          <p className="mt-2 break-all text-sm text-stone-500">{document.original_filename}</p>
        </div>
        <div className="flex gap-2">
          <span className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600">
            {label(document.life_area)}
          </span>
          <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">
            {label(document.status)}
          </span>
        </div>
      </div>
      {document.status === "failed" ? (
        <div className="mt-6 flex flex-col justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center">
          <div>
            <p className="text-sm font-medium text-amber-900">Processing failed</p>
            <p className="mt-1 text-xs text-amber-700">
              The original is safe. Check the local processing configuration, then retry.
            </p>
          </div>
          <RetryProcessingButton documentId={document.id} />
        </div>
      ) : null}
      <section className="panel mt-6 overflow-hidden">
        <div className="flex min-h-11 items-center justify-between gap-3 border-b border-stone-200 bg-white px-4 py-2 text-xs font-medium text-stone-500">
          <span>Original document</span>
          <span className="flex items-center gap-1.5 text-[11px] font-normal text-stone-400"><ShieldCheck className="size-3.5" />Protected local delivery</span>
        </div>
        <DocumentPreview documentId={document.id} mimeType={document.mime_type} title={document.title} initialPage={initialPage} heightClass="h-[72vh] min-h-[520px] max-h-[900px]" />
      </section>
      <ExtractionReviewPanel documentId={document.id} history={extractionHistory} />
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(260px,0.36fr)_minmax(0,1fr)]">
        <section className="panel p-5">
          <h2 className="text-sm font-semibold text-stone-900">Document information</h2>
          <dl className="mt-5 space-y-5">
            {metadata.map(([Icon, term, value]) => (
              <div key={term} className="grid grid-cols-[20px_1fr] gap-3">
                <Icon className="mt-0.5 size-4 text-stone-400" />
                <div>
                  <dt className="text-xs text-stone-400">{term}</dt>
                  <dd
                    className={`mt-1 text-sm text-stone-700 ${
                      term === "SHA-256" ? "break-all font-mono text-[11px] leading-5" : ""
                    }`}
                  >
                    {value}
                  </dd>
                </div>
              </div>
            ))}
          </dl>
        </section>
        <section className="panel p-5">
          <h2 className="text-sm font-semibold text-stone-900">Document status</h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <StatusFact label="Processing" value={label(document.status)} />
            <StatusFact label="Life area" value={label(document.life_area)} />
            <StatusFact label="Document type" value={document.document_type ? label(document.document_type) : "Not confirmed"} />
          </div>
          <p className="mt-5 border-t border-stone-100 pt-4 text-xs leading-5 text-stone-500">The viewer shows the immutable source file. Extracted text, metadata, and knowledge remain reviewable layers with their own provenance.</p>
        </section>
      </div>
    </div>
  );
}

function StatusFact({ label: term, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-stone-50 p-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-stone-400">{term}</p><p className="mt-1 break-words text-sm font-medium text-stone-800">{value}</p></div>;
}
