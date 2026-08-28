import { UpcomingWorkspace } from "@/components/upcoming-workspace";
import { getKnowledgeReview, getUpcoming } from "@/lib/api/server";

export const metadata = { title: "Upcoming" };

export default async function UpcomingPage() {
  const [snapshot, pendingDeadlines, pendingActions] = await Promise.all([
    getUpcoming(),
    getKnowledgeReview("deadline"),
    getKnowledgeReview("action_item"),
  ]);
  return <UpcomingWorkspace snapshot={snapshot} pending={pendingDeadlines.total + pendingActions.total} />;
}
