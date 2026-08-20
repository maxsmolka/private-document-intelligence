import { ArrowRight, FileText, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";

export default function OverviewPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-10 md:px-8 md:py-16">
      <p className="mb-3 text-sm font-medium text-stone-500">Overview</p>
      <h1 className="max-w-2xl text-4xl font-semibold tracking-[-0.04em] text-stone-950 md:text-5xl">Your documents, quietly organized.</h1>
      <p className="mt-5 max-w-xl text-base leading-7 text-stone-500">A private home for the files that run your life. Start with upload and retrieval; local intelligence arrives next.</p>
      <Link href="/documents" className="mt-8 inline-flex items-center gap-2 rounded-lg bg-stone-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-stone-800">
        Open documents <ArrowRight className="size-4" />
      </Link>
      <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-stone-200 bg-stone-200 md:grid-cols-3">
        {[
          [FileText, "One calm archive", "PDFs and images live together with useful metadata."],
          [ShieldCheck, "Private by design", "Files stay on the storage and database you control."],
          [Sparkles, "Built to grow", "OCR, extraction, and local models fit into the next milestones."],
        ].map(([Icon, title, copy]) => {
          const FeatureIcon = Icon as typeof FileText;
          return <div key={title as string} className="bg-[#fbfaf7] p-6"><FeatureIcon className="mb-8 size-5 text-stone-500" /><h2 className="font-medium text-stone-900">{title as string}</h2><p className="mt-2 text-sm leading-6 text-stone-500">{copy as string}</p></div>;
        })}
      </div>
    </div>
  );
}

