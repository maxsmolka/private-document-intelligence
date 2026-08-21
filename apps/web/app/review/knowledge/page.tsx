import { KnowledgeShell } from "@/components/knowledge-shell";
import { KnowledgeReviewWorkspace } from "@/components/knowledge-review-workspace";
import { getKnowledgeReview } from "@/lib/api/server";

export const metadata = { title: "Knowledge review" };
export default async function KnowledgeReviewPage() { const data = await getKnowledgeReview(); return <KnowledgeShell eyebrow="Review" title="Knowledge proposals" description="Accept, link, edit in a future field workflow, or reject evidence-backed entity and life-model candidates."><KnowledgeReviewWorkspace proposals={data.items} /></KnowledgeShell>; }
