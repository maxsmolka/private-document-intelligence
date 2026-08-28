import { KnowledgeShell } from "@/components/knowledge-shell";
import { KnowledgeReviewWorkspace } from "@/components/knowledge-review-workspace";
import { Button } from "@/components/ui/button";
import { getKnowledgeReview } from "@/lib/api/server";

export const metadata = { title: "Knowledge review" };

interface ReviewParameters {
  proposal_type?: string;
  document_type?: string;
  confidence_min?: string;
  confidence_max?: string;
  sort?: string;
}

const proposalTypes = [
  "deadline",
  "action_item",
  "contract",
  "event",
  "organization",
  "document_relationship",
];

export default async function KnowledgeReviewPage({ searchParams }: { searchParams: Promise<ReviewParameters> }) {
  const filters = await searchParams;
  const data = await getKnowledgeReview({
    proposalType: filters.proposal_type,
    documentType: filters.document_type,
    confidenceMin: filters.confidence_min,
    confidenceMax: filters.confidence_max,
    sort: filters.sort ?? "priority",
  });
  return <KnowledgeShell eyebrow="Knowledge review" title="Canonical knowledge proposals" description="Review entities, events, contracts, relationships, deadlines, and actions derived from document evidence. This queue is separate from document metadata review.">
    <form method="get" className="mb-5 grid gap-3 rounded-xl border border-stone-200 bg-white p-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Knowledge review filters">
      <label className="text-xs font-medium text-stone-600">Proposal type<select name="proposal_type" defaultValue={filters.proposal_type ?? ""} className="field mt-1"><option value="">All proposal types</option>{proposalTypes.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
      <label className="text-xs font-medium text-stone-600">Document type<input name="document_type" defaultValue={filters.document_type ?? ""} className="field mt-1" placeholder="All document types" /></label>
      <label className="text-xs font-medium text-stone-600">Minimum confidence<select name="confidence_min" defaultValue={filters.confidence_min ?? ""} className="field mt-1"><option value="">Any confidence</option><option value="0.9">90%+</option><option value="0.75">75%+</option><option value="0.5">50%+</option></select></label>
      <label className="text-xs font-medium text-stone-600">Sort<select name="sort" defaultValue={filters.sort ?? "priority"} className="field mt-1"><option value="priority">Priority first</option><option value="confidence_desc">Highest confidence</option><option value="confidence_asc">Lowest confidence</option><option value="oldest">Oldest first</option><option value="newest">Newest first</option></select></label>
      <div className="flex items-end gap-2"><Button type="submit" className="h-10">Apply filters</Button><a href="/review/knowledge" className="inline-flex h-10 cursor-pointer items-center justify-center rounded-lg border border-stone-200 bg-white px-3.5 text-sm font-medium text-stone-700 transition hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400">Reset</a></div>
    </form>
    <p className="mb-4 text-xs text-stone-500">{data.total} matching proposals · deadline and action candidates rank first by default. Every decision remains proposal-scoped; no mass accept is available.</p>
    <KnowledgeReviewWorkspace proposals={data.items} />
  </KnowledgeShell>;
}
