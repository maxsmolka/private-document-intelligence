import Link from "next/link";
import { notFound } from "next/navigation";
import { KnowledgeShell } from "@/components/knowledge-shell";
import { ApiError } from "@/lib/api/documents";
import { getOrganization } from "@/lib/api/server";

export default async function OrganizationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let item;
  try { item = await getOrganization(id); }
  catch (error) { if (error instanceof ApiError && error.status === 404) notFound(); throw error; }
  return <KnowledgeShell eyebrow="Organization" title={item.canonical_name} description="Canonical, review-confirmed organization knowledge with source-backed relationships."><dl className="panel grid gap-px overflow-hidden bg-stone-100 text-sm sm:grid-cols-3"><Fact label="Aliases" value={item.aliases.join(", ") || "None"} /><Fact label="Documents" value={String(item.document_ids.length)} /><Fact label="Contracts" value={String(item.contract_ids.length)} /><Fact label="Events" value={String(item.event_ids.length)} /><Fact label="Deadlines" value={String(item.deadline_ids.length)} /><Fact label="Open actions" value={String(item.action_item_ids.length)} /></dl><section className="mt-8"><h2 className="text-sm font-medium text-stone-900">Source documents</h2><div className="panel mt-2 divide-y divide-stone-100 overflow-hidden">{item.document_ids.map((document) => <Link key={document} href={`/documents/${document}`} className="block px-4 py-3 text-sm text-stone-600 hover:bg-stone-50 hover:text-stone-950">Document {document.slice(0, 8)} →</Link>)}</div></section><section className="mt-8"><h2 className="text-sm font-medium text-stone-900">Related contracts</h2><div className="panel mt-2 divide-y divide-stone-100 overflow-hidden">{item.contract_ids.map((contract) => <Link key={contract} href={`/contracts/${contract}`} className="block px-4 py-3 text-sm text-stone-600 hover:bg-stone-50 hover:text-stone-950">Contract {contract.slice(0, 8)} →</Link>)}</div></section></KnowledgeShell>;
}
function Fact({ label, value }: { label: string; value: string }) { return <div className="bg-white p-5"><dt className="text-xs uppercase tracking-wide text-stone-400">{label}</dt><dd className="mt-1 break-words text-stone-800">{value}</dd></div>; }
