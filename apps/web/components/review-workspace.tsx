"use client";

import { AlertTriangle, ArrowRight, Check, FileText, RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  confirmReview,
  documentContentUrl,
  rejectReview,
  retryDocument,
  type ConfirmMetadata,
  type LifeArea,
  type ReviewDetail,
  type ReviewItem,
} from "@/lib/api/documents";

const areas: LifeArea[] = ["finance", "insurance", "vehicle", "home", "health", "tax", "work", "travel", "personal", "other"];
function label(value: string) { return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()); }

export function ReviewWorkspace({ detail, queue }: { detail: ReviewDetail; queue: ReviewItem[] }) {
  const router = useRouter();
  const document = detail.document;
  const proposed = useMemo(() => Object.fromEntries(detail.proposals.filter((item) => item.status === "pending").map((item) => [item.field_name, item.proposed_value])), [detail.proposals]);
  const [values, setValues] = useState<ConfirmMetadata>({
    title: proposed.title ?? document.title,
    document_date: proposed.document_date ?? document.document_date,
    life_area: (proposed.life_area as LifeArea | undefined) ?? document.life_area,
    document_type: proposed.document_type ?? document.document_type,
  });
  const [busy, setBusy] = useState<"confirm" | "retry" | "reject" | null>(null);
  const [error, setError] = useState("");
  const next = queue.find((item) => item.document.id !== document.id)?.document.id;
  const ocrAsset = detail.assets.find((asset) => asset.kind === "ocr_pdf");

  async function confirm(event: FormEvent) {
    event.preventDefault(); setBusy("confirm"); setError("");
    try { await confirmReview(document.id, values); router.push(next ? `/review?id=${next}` : "/review"); router.refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save review"); setBusy(null); }
  }
  async function retry() {
    setBusy("retry"); setError("");
    try { await retryDocument(document.id); router.push("/documents"); router.refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not retry processing"); setBusy(null); }
  }
  async function reject() {
    setBusy("reject"); setError("");
    try { await rejectReview(document.id); router.refresh(); setBusy(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not reject proposals"); setBusy(null); }
  }

  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
    <section className="min-h-[72vh] overflow-hidden rounded-2xl border border-stone-200 bg-stone-100 shadow-sm"><div className="flex h-12 items-center justify-between border-b border-stone-200 bg-white px-4"><span className="text-xs font-medium text-stone-500">Original document</span><Link href={`/documents/${document.id}`} className="text-xs text-stone-400 hover:text-stone-700">Open details</Link></div>{document.mime_type.startsWith("image/") ? <div className="grid min-h-[calc(72vh-3rem)] place-items-center p-5"><img src={documentContentUrl(document.id)} alt={`Preview of ${document.title}`} className="max-h-[66vh] max-w-full rounded shadow-xl" /></div> : <iframe src={documentContentUrl(document.id)} title={`Preview of ${document.title}`} className="h-[calc(72vh-3rem)] w-full border-0" />}</section>
    <form onSubmit={confirm} className="space-y-5"><div><div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-stone-400"><Sparkles className="size-3.5" />Review metadata</div><h2 className="mt-2 text-xl font-semibold tracking-tight text-stone-950">Confirm what PDI found</h2><p className="mt-1 text-sm leading-6 text-stone-500">Machine proposals never replace canonical metadata until you save.</p></div>
      {detail.extraction?.warnings.length ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-3"><div className="flex gap-2 text-xs font-medium text-amber-800"><AlertTriangle className="mt-0.5 size-3.5" />Processing notes</div><ul className="mt-2 space-y-1 text-xs text-amber-700">{detail.extraction.warnings.map((warning) => <li key={warning}>{label(warning)}</li>)}</ul></div> : null}
      <div className="space-y-4 rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <Field label="Title" proposed={proposed.title}><input required maxLength={255} value={values.title} onChange={(event) => setValues({ ...values, title: event.target.value })} className="field" /></Field>
        <Field label="Document date" proposed={proposed.document_date}><input type="date" value={values.document_date ?? ""} onChange={(event) => setValues({ ...values, document_date: event.target.value || null })} className="field" /></Field>
        <Field label="Life area" proposed={proposed.life_area}><select value={values.life_area} onChange={(event) => setValues({ ...values, life_area: event.target.value as LifeArea })} className="field">{areas.map((area) => <option key={area} value={area}>{label(area)}</option>)}</select></Field>
        <Field label="Document type" proposed={proposed.document_type}><input maxLength={100} placeholder="e.g. Invoice" value={values.document_type ?? ""} onChange={(event) => setValues({ ...values, document_type: event.target.value || null })} className="field" /></Field>
      </div>
      {detail.extraction ? <div className="rounded-2xl border border-stone-200 bg-white p-4"><div className="flex items-center justify-between"><span className="flex items-center gap-2 text-xs font-medium text-stone-500"><FileText className="size-3.5" />Extracted text</span><span className="text-[11px] text-stone-400">{detail.extraction.provider} · {detail.extraction.page_count} {detail.extraction.page_count === 1 ? "page" : "pages"}</span></div>{ocrAsset ? <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg bg-stone-50 p-3 text-[11px] text-stone-500"><span>OCR</span><span className="text-right text-stone-700">Completed</span><span>Provider</span><span className="text-right text-stone-700">{ocrAsset.provider}</span></div> : null}<p className="mt-3 max-h-28 overflow-hidden whitespace-pre-wrap text-xs leading-5 text-stone-500">{detail.extraction.text || "No embedded text was found. This document is an OCR candidate."}</p></div> : null}
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy !== null}><Check className="size-4" />{busy === "confirm" ? "Saving…" : "Save & Confirm"}</Button><Button type="button" variant="secondary" onClick={retry} disabled={busy !== null}><RotateCcw className="size-4" />{busy === "retry" ? "Queuing…" : "Retry processing"}</Button>{next ? <Link href={`/review?id=${next}`} className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm text-stone-500 hover:bg-stone-100">Skip <ArrowRight className="size-4" /></Link> : null}</div>
      {detail.proposals.some((item) => item.status === "pending") ? <button type="button" onClick={reject} disabled={busy !== null} className="text-xs text-stone-400 underline-offset-4 hover:text-stone-700 hover:underline">Reject machine proposals</button> : null}
    </form>
  </div>;
}

function Field({ label: fieldLabel, proposed, children }: { label: string; proposed?: string | null; children: React.ReactNode }) {
  return <label className="block"><span className="flex items-center justify-between text-xs font-medium text-stone-600">{fieldLabel}{proposed != null ? <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-600">Proposed</span> : null}</span><span className="mt-1.5 block">{children}</span></label>;
}
