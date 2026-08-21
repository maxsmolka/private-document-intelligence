import Link from "next/link";
import { KnowledgeShell, label } from "@/components/knowledge-shell";
import { getContracts } from "@/lib/api/server";

export const metadata = { title: "Contracts" };
export default async function ContractsPage() { const data = await getContracts(); return <KnowledgeShell eyebrow="Knowledge" title="Contracts" description="Partial and complete contracts assembled incrementally from reviewed document evidence.">{data.items.length ? <div className="divide-y divide-stone-200 border-y border-stone-200">{data.items.map((item) => <Link key={item.id} href={`/contracts/${item.id}`} className="flex items-start justify-between gap-4 px-2 py-4 hover:bg-stone-100/60"><div><h2 className="text-sm font-medium text-stone-900">{item.title}</h2><p className="mt-1 text-xs text-stone-400">{label(item.contract_type)}{item.reference_identifier ? ` · ${item.reference_identifier}` : ""}</p></div><span className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-stone-500">{label(item.status)}</span></Link>)}</div> : <p className="py-16 text-center text-sm text-stone-400">No reviewed contracts yet.</p>}</KnowledgeShell>; }
