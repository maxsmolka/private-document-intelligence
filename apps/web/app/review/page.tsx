import { CheckCircle2, FileCheck2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { ReviewWorkspace } from "@/components/review-workspace";
import { getReviewDetail, getReviewQueue } from "@/lib/api/server";

export const metadata: Metadata = { title: "Review" };

export default async function ReviewPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const { id } = await searchParams;
  let queue;
  try { queue = await getReviewQueue(); } catch { queue = { items: [], total: 0, limit: 50, offset: 0 }; }
  if (!queue.items.length) return <div className="page grid min-h-[calc(100vh-4rem)] max-w-lg place-items-center text-center"><div><span className="mx-auto grid size-12 place-items-center rounded-2xl bg-emerald-50 text-emerald-700"><CheckCircle2 className="size-6" /></span><h1 className="mt-5 text-2xl font-semibold tracking-tight text-stone-950">Document review is clear</h1><p className="mt-2 text-sm leading-6 text-stone-500">No documents need metadata confirmation. Knowledge and extraction decisions remain in their own review layers.</p><Link href="/documents" className="mt-6 inline-flex rounded-lg border border-stone-200 bg-white px-3.5 py-2 text-sm font-medium text-stone-700 shadow-sm">View documents</Link></div></div>;
  const selected = queue.items.some((item) => item.document.id === id) ? id! : queue.items[0].document.id;
  const detail = await getReviewDetail(selected);
  return <div className="page max-w-[1500px]"><div className="mb-7 flex items-end justify-between gap-4"><div className="min-w-0"><div className="eyebrow flex items-center gap-2 text-violet-600"><FileCheck2 className="size-4" />Document review</div><h1 className="mt-2 line-clamp-2 break-words text-2xl font-semibold tracking-[-0.025em] text-stone-950" title={detail.document.title}>{detail.document.title}</h1><p className="mt-1 text-sm text-stone-500">Confirm metadata while keeping extraction and knowledge decisions separate.</p></div><span className="status-pill shrink-0 border-violet-200 bg-violet-50 text-violet-700">{queue.total} {queue.total === 1 ? "document" : "documents"} remaining</span></div><ReviewWorkspace key={selected} detail={detail} queue={queue.items} /></div>;
}
