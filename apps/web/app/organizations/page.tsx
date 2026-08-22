import Link from "next/link";
import { Building2 } from "lucide-react";
import { KnowledgeShell, label } from "@/components/knowledge-shell";
import { getOrganizations } from "@/lib/api/server";

export const metadata = { title: "Organizations" };
export default async function OrganizationsPage() {
  const data = await getOrganizations();
  return <KnowledgeShell eyebrow="Knowledge" title="Organizations" description="Reviewed organizations derived from source documents. Similar names remain separate until explicitly resolved.">{data.items.length ? <div className="panel divide-y divide-stone-100 overflow-hidden">{data.items.map((item) => <Link key={item.id} href={`/organizations/${item.id}`} className="flex items-center gap-4 px-5 py-4 hover:bg-stone-50"><span className="grid size-10 place-items-center rounded-xl bg-emerald-50 text-emerald-800"><Building2 className="size-4" /></span><div className="min-w-0 flex-1"><h2 className="truncate text-sm font-medium text-stone-900" title={item.canonical_name}>{item.canonical_name}</h2><p className="mt-0.5 text-xs text-stone-400">{item.organization_type ? label(item.organization_type) : "Organization"}</p></div><span className="text-xs font-medium text-emerald-800">Open →</span></Link>)}</div> : <div className="empty-state"><p className="text-sm text-stone-500">No reviewed organizations yet.</p></div>}</KnowledgeShell>;
}
