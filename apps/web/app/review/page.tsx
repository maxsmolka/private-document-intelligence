import { CheckCircle2, FileCheck2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { ReviewWorkspace } from "@/components/review-workspace";
import { getReviewDetail, getReviewQueue } from "@/lib/api/documents";

export const metadata: Metadata = { title: "Review" };

export default async function ReviewPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const { id } = await searchParams;
  let queue;
  try { queue = await getReviewQueue(); } catch { queue = { items: [], total: 0, limit: 50, offset: 0 }; }
  if (!queue.items.length) return <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-lg place-items-center px-6 text-center"><div><span className="mx-auto grid size-12 place-items-center rounded-2xl bg-emerald-50 text-emerald-600"><CheckCircle2 className="size-6" /></span><h1 className="mt-5 text-2xl font-semibold tracking-tight text-stone-950">Review queue is clear</h1><p className="mt-2 text-sm leading-6 text-stone-500">Newly processed documents will appear here before becoming canonical.</p><Link href="/documents" className="mt-6 inline-flex rounded-lg border border-stone-200 bg-white px-3.5 py-2 text-sm font-medium text-stone-700 shadow-sm">View documents</Link></div></div>;
  const selected = queue.items.some((item) => item.document.id === id) ? id! : queue.items[0].document.id;
  const detail = await getReviewDetail(selected);
  return <div className="mx-auto max-w-[1500px] px-5 py-8 md:px-8"><div className="mb-7 flex items-end justify-between"><div><div className="flex items-center gap-2 text-sm font-medium text-stone-500"><FileCheck2 className="size-4" />Review queue</div><h1 className="mt-2 text-2xl font-semibold tracking-[-0.025em] text-stone-950">{detail.document.title}</h1></div><span className="rounded-full border border-stone-200 bg-white px-3 py-1 text-xs text-stone-500">{queue.total} remaining</span></div><ReviewWorkspace key={selected} detail={detail} queue={queue.items} /></div>;
}

