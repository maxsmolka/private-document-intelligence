import { KnowledgeShell } from "@/components/knowledge-shell";
import { KnowledgeReviewWorkspace } from "@/components/knowledge-review-workspace";
import { getKnowledgeReview } from "@/lib/api/server";

export const metadata = { title: "Knowledge review" };
export default async function KnowledgeReviewPage() { const data = await getKnowledgeReview(); return <KnowledgeShell eyebrow="Knowledge review" title="Canonical knowledge proposals" description="Review entities, events, contracts, relationships, deadlines, and actions derived from document evidence. This queue is separate from document metadata review."><KnowledgeReviewWorkspace proposals={data.items} /></KnowledgeShell>; }
