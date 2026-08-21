"use client";

import { AlertTriangle, ArrowRight, Check, FileText, Pencil, RotateCcw, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import { DocumentPreview } from "@/components/document-preview";
import { Button } from "@/components/ui/button";
import {
  acceptProposal,
  confirmReview,
  rejectReview,
  rejectProposal,
  retryDocument,
  type ConfirmMetadata,
  type LifeArea,
  type MetadataProposal,
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
  const [busy, setBusy] = useState<string | null>(null);
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
  async function decide(proposal: MetadataProposal, action: "accept" | "reject", value?: string) {
    setBusy(proposal.id); setError("");
    try {
      if (action === "accept") {
        await acceptProposal(document.id, proposal.id, value);
        const accepted = value ?? proposal.normalized_value ?? proposal.proposed_value;
        if (["title", "document_date", "life_area", "document_type"].includes(proposal.field_name)) {
          setValues((current) => ({ ...current, [proposal.field_name]: accepted }));
        }
      } else {
        await rejectProposal(document.id, proposal.id);
        if (["title", "document_date", "life_area", "document_type"].includes(proposal.field_name)) {
          setValues((current) => ({ ...current, [proposal.field_name]: document[proposal.field_name as keyof typeof document] }));
        }
      }
      router.refresh(); setBusy(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update proposal"); setBusy(null); }
  }

  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
    <section className="min-h-[72vh] overflow-hidden rounded-2xl border border-stone-200 bg-stone-100 shadow-sm"><div className="flex h-12 items-center justify-between border-b border-stone-200 bg-white px-4"><span className="text-xs font-medium text-stone-500">Original document</span><Link href={`/documents/${document.id}`} className="text-xs text-stone-400 hover:text-stone-700">Open details</Link></div><DocumentPreview documentId={document.id} mimeType={document.mime_type} title={document.title} heightClass="min-h-[calc(72vh-3rem)] h-[calc(72vh-3rem)]" /></section>
    <form onSubmit={confirm} className="space-y-5"><div><div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-stone-400"><Sparkles className="size-3.5" />Review metadata</div><h2 className="mt-2 text-xl font-semibold tracking-tight text-stone-950">Confirm what PDI found</h2><p className="mt-1 text-sm leading-6 text-stone-500">Machine proposals never replace canonical metadata until you save.</p></div>
      {detail.extraction?.warnings.length ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-3"><div className="flex gap-2 text-xs font-medium text-amber-800"><AlertTriangle className="mt-0.5 size-3.5" />Processing notes</div><ul className="mt-2 space-y-1 text-xs text-amber-700">{detail.extraction.warnings.map((warning) => <li key={warning}>{label(warning)}</li>)}</ul></div> : null}
      <div className="space-y-4 rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
        <Field label="Title" proposed={proposed.title}><input required maxLength={255} value={values.title} onChange={(event) => setValues({ ...values, title: event.target.value })} className="field" /></Field>
        <Field label="Document date" proposed={proposed.document_date}><input type="date" value={values.document_date ?? ""} onChange={(event) => setValues({ ...values, document_date: event.target.value || null })} className="field" /></Field>
        <Field label="Life area" proposed={proposed.life_area}><select value={values.life_area} onChange={(event) => setValues({ ...values, life_area: event.target.value as LifeArea })} className="field">{areas.map((area) => <option key={area} value={area}>{label(area)}</option>)}</select></Field>
        <Field label="Document type" proposed={proposed.document_type}><input maxLength={100} placeholder="e.g. Invoice" value={values.document_type ?? ""} onChange={(event) => setValues({ ...values, document_type: event.target.value || null })} className="field" /></Field>
      </div>
      {detail.proposals.some((item) => item.status === "pending" && item.intelligence_run_id) ? <div className="space-y-3"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-stone-800">Evidence-backed proposals</h3>{detail.current_intelligence_run ? <span className="text-[11px] text-stone-400">{detail.current_intelligence_run.provider} · schema {detail.current_intelligence_run.schema_version}</span> : null}</div>{detail.proposals.filter((item) => item.status === "pending" && item.intelligence_run_id).map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} busy={busy === proposal.id} decide={decide} />)}</div> : null}
      {detail.extraction ? <div className="rounded-2xl border border-stone-200 bg-white p-4"><div className="flex items-center justify-between"><span className="flex items-center gap-2 text-xs font-medium text-stone-500"><FileText className="size-3.5" />Extracted text</span><span className="text-[11px] text-stone-400">{detail.extraction.provider} · {detail.extraction.page_count} {detail.extraction.page_count === 1 ? "page" : "pages"}</span></div>{ocrAsset ? <div className="mt-3 grid grid-cols-2 gap-2 rounded-lg bg-stone-50 p-3 text-[11px] text-stone-500"><span>OCR</span><span className="text-right text-stone-700">Completed</span><span>Provider</span><span className="text-right text-stone-700">{ocrAsset.provider}</span></div> : null}<p className="mt-3 max-h-28 overflow-hidden whitespace-pre-wrap text-xs leading-5 text-stone-500">{detail.extraction.text || "No embedded text was found. This document is an OCR candidate."}</p></div> : null}
      {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
      <div className="flex flex-wrap gap-2"><Button type="submit" disabled={busy !== null}><Check className="size-4" />{busy === "confirm" ? "Saving…" : "Save & Confirm"}</Button><Button type="button" variant="secondary" onClick={retry} disabled={busy !== null}><RotateCcw className="size-4" />{busy === "retry" ? "Queuing…" : "Retry processing"}</Button>{next ? <Link href={`/review?id=${next}`} className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm text-stone-500 hover:bg-stone-100">Skip <ArrowRight className="size-4" /></Link> : null}</div>
      {detail.proposals.some((item) => item.status === "pending") ? <button type="button" onClick={reject} disabled={busy !== null} className="text-xs text-stone-400 underline-offset-4 hover:text-stone-700 hover:underline">Reject machine proposals</button> : null}
    </form>
  </div>;
}

function ProposalCard({ proposal, busy, decide }: { proposal: MetadataProposal; busy: boolean; decide: (proposal: MetadataProposal, action: "accept" | "reject", value?: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(proposal.normalized_value ?? proposal.proposed_value ?? "");
  const confidence = proposal.confidence == null ? "Unknown" : proposal.confidence >= 0.85 ? "High" : proposal.confidence >= 0.65 ? "Medium" : "Low";
  const tone = confidence === "High" ? "bg-emerald-50 text-emerald-700" : confidence === "Medium" ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700";
  return <article className="rounded-xl border border-stone-200 bg-white p-4 shadow-sm"><div className="flex items-start justify-between gap-3"><div><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-semibold text-stone-700">{label(proposal.field_name)}</span><span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>{confidence}{proposal.confidence == null ? "" : ` ${Math.round(proposal.confidence * 100)}%`}</span>{proposal.is_critical ? <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-600">Verify carefully</span> : null}</div>{editing ? <input autoFocus value={value} onChange={(event) => setValue(event.target.value)} className="field mt-2" /> : <p className="mt-1 text-sm font-medium text-stone-950">{proposal.normalized_value ?? proposal.proposed_value}</p>}</div><span className="text-[10px] text-stone-400">{proposal.provider}</span></div>{proposal.evidence.length ? <div className="mt-3 rounded-lg bg-stone-50 p-3"><div className="text-[10px] font-medium uppercase tracking-wide text-stone-400">Evidence · page {proposal.evidence[0].page}</div><p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-stone-600">“{proposal.evidence[0].text}”</p></div> : null}{proposal.validation_notes.includes("ocr_sensitive_value") ? <p className="mt-2 text-[11px] text-amber-700">OCR-sensitive value; compare it with the original.</p> : null}<div className="mt-3 flex gap-2"><Button type="button" onClick={() => void decide(proposal, "accept", editing ? value : undefined)} disabled={busy || !proposal.evidence_verified}><Check className="size-3.5" />{busy ? "Saving…" : "Accept"}</Button><Button type="button" variant="secondary" onClick={() => setEditing(!editing)} disabled={busy}><Pencil className="size-3.5" />{editing ? "Cancel edit" : "Edit"}</Button><button type="button" onClick={() => void decide(proposal, "reject")} disabled={busy} className="inline-flex items-center gap-1 px-2 text-xs text-stone-400 hover:text-red-600"><X className="size-3.5" />Reject</button></div></article>;
}

function Field({ label: fieldLabel, proposed, children }: { label: string; proposed?: string | null; children: React.ReactNode }) {
  return <label className="block"><span className="flex items-center justify-between text-xs font-medium text-stone-600">{fieldLabel}{proposed != null ? <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-600">Proposed</span> : null}</span><span className="mt-1.5 block">{children}</span></label>;
}
