import Link from "next/link";
import { Building2 } from "lucide-react";
import { KnowledgeShell, label } from "@/components/knowledge-shell";
import { getOrganizations } from "@/lib/api/server";

export const metadata = { title: "Organizations" };
export default async function OrganizationsPage() {
  const data = await getOrganizations().catch(() => ({ items: [], total: 0, limit: 50, offset: 0 }));
  return <KnowledgeShell eyebrow="Knowledge" title="Organizations" description="Reviewed organizations derived from source documents. Similar names remain separate until explicitly resolved.">{data.items.length ? <div className="divide-y divide-stone-200 border-y border-stone-200">{data.items.map((item) => <Link key={item.id} href={`/organizations/${item.id}`} className="flex items-center gap-4 px-2 py-4 hover:bg-stone-100/60"><span className="grid size-9 place-items-center rounded-lg bg-stone-100 text-stone-500"><Building2 className="size-4" /></span><div className="min-w-0 flex-1"><h2 className="truncate text-sm font-medium text-stone-900">{item.canonical_name}</h2><p className="mt-0.5 text-xs text-stone-400">{item.organization_type ? label(item.organization_type) : "Organization"}</p></div><span className="text-xs text-stone-400">Open →</span></Link>)}</div> : <p className="py-16 text-center text-sm text-stone-400">No reviewed organizations yet.</p>}</KnowledgeShell>;
}
