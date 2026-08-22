"use client";

import { CheckCircle2, GitCompareArrows, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  promoteExtraction,
  keepCurrentExtraction,
  type ExtractionHistory,
  type ExtractionVersion,
} from "@/lib/api/documents";

function percent(value: number | null | undefined) {
  return value == null ? "Not available" : `${(value * 100).toFixed(1)}%`;
}

function Version({ item, title, description }: { item: ExtractionVersion; title: string; description: string }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-stone-50 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-stone-400">{title}</p>
      <p className="mt-1 text-xs text-stone-500">{description}</p>
      <p className="mt-2 text-sm font-semibold text-stone-800">{item.provider}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-stone-500">
        <dt>Source</dt><dd className="text-right text-stone-700">{item.source}</dd>
        <dt>Pages</dt><dd className="text-right text-stone-700">{item.page_count}</dd>
        <dt>Characters</dt><dd className="text-right text-stone-700">{item.character_count.toLocaleString("de-DE")}</dd>
        <dt>Created</dt><dd className="text-right text-stone-700">{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeZone: "Europe/Berlin" }).format(new Date(item.created_at))}</dd>
      </dl>
      {item.warnings.length ? <p className="mt-3 text-xs text-amber-700">{item.warnings.join(" · ")}</p> : null}
    </div>
  );
}

export function ExtractionReviewPanel({ documentId, history }: { documentId: string; history: ExtractionHistory }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState(false);
  const [error, setError] = useState("");
  const current = history.versions.find((item) => item.canonical);
  const candidate = [...history.versions].reverse().find((item) => !item.canonical && item.source === "pdi");
  if (!current || !candidate || kept) return null;
  const comparison = [...history.comparisons].reverse().find(
    (item) => item.baseline_extraction_id === current.id && item.candidate_extraction_id === candidate.id,
  );

  async function promote() {
    setBusy(true); setError("");
    try {
      await promoteExtraction(documentId, candidate!.id, comparison?.id ?? null);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not promote extraction");
      setBusy(false);
    }
  }

  async function keepCurrent() {
    if (!comparison) return;
    setBusy(true); setError("");
    try {
      await keepCurrentExtraction(documentId, comparison.id);
      setKept(true);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save review decision");
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 rounded-2xl border border-violet-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="grid size-9 place-items-center rounded-lg bg-violet-50 text-violet-700"><GitCompareArrows className="size-4" /></span>
        <div><h2 className="text-sm font-semibold text-stone-900">Extraction review</h2><p className="mt-1 text-xs leading-5 text-stone-500">Choose which text version PDI should use for search and future analysis. The original file never changes.</p></div>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2"><Version item={current} title="Current text version" description="Used by search now." /><Version item={candidate} title="New PDI text version" description="Newly regenerated; not yet canonical." /></div>
      {comparison ? <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl border border-stone-200 p-4 text-xs sm:grid-cols-4"><div><p className="text-stone-400">Similarity</p><p className="mt-1 font-medium text-stone-800">{percent(comparison.metrics.similarity)}</p></div><div><p className="text-stone-400">Text coverage</p><p className="mt-1 font-medium text-stone-800">{percent(comparison.metrics.candidate_non_whitespace_coverage)}</p></div><div><p className="text-stone-400">Critical fields</p><p className="mt-1 font-medium text-stone-800">{percent(comparison.metrics.critical_field_preservation)}</p></div><div><p className="text-stone-400">Decision</p><p className="mt-1 flex items-center gap-1 font-medium text-stone-800">{comparison.status === "equivalent" ? <CheckCircle2 className="size-3.5 text-emerald-600" /> : <ShieldAlert className="size-3.5 text-amber-600" />}{comparison.status.replaceAll("_", " ")}</p></div></div> : <p className="mt-4 text-xs text-amber-700">Comparison metrics are not available yet. Keep the current extraction until processing finishes.</p>}
      {error ? <p role="alert" className="mt-3 text-xs text-red-600">{error}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2"><Button variant="secondary" onClick={() => void keepCurrent()} disabled={busy || !comparison}>Keep current text</Button><Button onClick={() => void promote()} disabled={busy || !comparison}>{busy ? "Saving…" : "Use PDI text version"}</Button></div>
      <p className="mt-2 text-[11px] leading-4 text-stone-400">Keeping current records the comparison decision. Using the PDI version makes it canonical and re-runs downstream analysis for review.</p>
    </section>
  );
}
