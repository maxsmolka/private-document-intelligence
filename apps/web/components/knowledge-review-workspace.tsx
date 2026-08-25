"use client";

import { Check, Link2, Pencil, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { label } from "@/components/knowledge-shell";
import { acceptKnowledge, rejectKnowledge, type KnowledgeProposal } from "@/lib/api/knowledge";

function editableField(item: KnowledgeProposal) {
  if (item.proposal_type === "organization") return "canonical_name";
  if (item.proposal_type === "document_relationship") return "relationship_type";
  return "title";
}

const actionableTypes = new Set(["organization", "contract", "document_relationship", "event", "deadline", "action_item"]);

function displayValue(item: KnowledgeProposal) {
  const field = editableField(item);
  return String(item.payload[field] ?? "Knowledge candidate");
}

export function KnowledgeReviewWorkspace({ proposals }: { proposals: KnowledgeProposal[] }) {
  const router = useRouter();
  const [pending, setPending] = useState(proposals);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [type, setType] = useState("all");

  async function decide(item: KnowledgeProposal, action: "create" | "link" | "reject") {
    setBusy(item.id);
    setError(null);
    try {
      if (action === "reject") {
        await rejectKnowledge(item.id);
      } else {
        const edited = edits[item.id];
        const values = edited === undefined ? {} : { [editableField(item)]: edited };
        await acceptKnowledge(
          item.id,
          action === "link" ? item.possible_existing_organization_id ?? undefined : undefined,
          values,
        );
      }
      setPending((current) => current.filter((proposal) => proposal.id !== item.id));
      setEditing(null);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Review failed");
    } finally {
      setBusy(null);
    }
  }

  if (!pending.length) {
    return <div className="empty-state"><p className="text-sm text-stone-500">No knowledge proposals await review.</p></div>;
  }
  const types = [...new Set(pending.map((item) => item.proposal_type))].sort();
  const visible = type === "all" ? pending : pending.filter((item) => item.proposal_type === type);
  const grouped = visible.reduce<Record<string, KnowledgeProposal[]>>((current, item) => {
    (current[item.proposal_type] ??= []).push(item);
    return current;
  }, {});
  return <div>
    {error ? <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
    <div className="mb-5 flex flex-col justify-between gap-3 rounded-xl border border-stone-200 bg-white p-4 sm:flex-row sm:items-center"><p className="text-xs leading-5 text-stone-500">{pending.length} {pending.length === 1 ? "knowledge proposal" : "knowledge proposals"} pending. Each decision is proposal-scoped.</p><select value={type} onChange={(event) => setType(event.target.value)} className="field sm:w-52" aria-label="Filter by proposal type"><option value="all">All proposal types</option>{types.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></div>
    <div className="space-y-7">
      {Object.entries(grouped).map(([group, items]) => <section key={group}><div className="mb-2 flex items-center justify-between"><h2 className="eyebrow text-stone-600">{label(group)}</h2><span className="text-xs text-stone-400">{items?.length ?? 0}</span></div><div className="panel divide-y divide-stone-100 overflow-hidden">{items?.map((item) => <article key={item.id} className="min-w-0 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wide text-stone-400">{label(item.proposal_type)}</p>
            {editing === item.id ? <label className="mt-2 block text-xs text-stone-500">
              Edit {label(editableField(item))}
              <input
                autoFocus
                value={edits[item.id] ?? displayValue(item)}
                onChange={(event) => setEdits((current) => ({ ...current, [item.id]: event.target.value }))}
                className="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm text-stone-900"
              />
            </label> : <h2 className="mt-1 break-words text-sm font-medium text-stone-900">{displayValue(item)}</h2>}
            <p className="mt-1 text-xs text-stone-400">{Math.round(item.confidence * 100)}% evidence strength{item.match_reason ? ` · ${item.match_reason}` : ""}</p>
            <Link href={`/documents/${item.document_id}`} className="mt-2 inline-block text-xs text-stone-500 hover:text-stone-900">Open source document →</Link>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
            {actionableTypes.has(item.proposal_type) ? <><button disabled={busy === item.id || !item.evidence_verified} onClick={() => decide(item, item.possible_existing_organization_id ? "link" : "create")} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-stone-900 px-3 text-xs font-medium text-white disabled:cursor-not-allowed disabled:bg-stone-300">{item.possible_existing_organization_id ? <Link2 className="size-3.5" /> : <Check className="size-3.5" />}{item.possible_existing_organization_id ? "Link existing" : "Accept"}</button>
            <button disabled={busy === item.id || !item.evidence_verified} onClick={() => setEditing(editing === item.id ? null : item.id)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-stone-200 px-3 text-xs text-stone-600 disabled:cursor-not-allowed disabled:text-stone-300"><Pencil className="size-3.5" />Edit</button></> : null}
            <button disabled={busy === item.id} onClick={() => decide(item, "reject")} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-stone-200 px-3 text-xs text-stone-500 hover:border-red-200 hover:text-red-700"><X className="size-3.5" />Reject</button>
          </div>
        </div>
        {item.evidence.map((span, index) => <blockquote key={index} className="mt-3 border-l-2 border-amber-200 pl-3 text-sm text-stone-600">“{span.text}” <Link href={`/documents/${item.document_id}?page=${span.page}`} className="ml-1 text-xs font-medium text-emerald-800 hover:underline">Page {span.page} · Show in document →</Link></blockquote>)}
        {!actionableTypes.has(item.proposal_type) ? <p className="mt-3 text-xs text-stone-500">This proposal is informational and can only be rejected here.</p> : !item.evidence_verified ? <p className="mt-3 text-xs text-amber-700">Accept and edit require verified source evidence. Reject remains available.</p> : null}
        {item.validation_notes.length ? <p className="mt-3 text-xs text-stone-400">Validation: {item.validation_notes.map(label).join(" · ")}</p> : null}
      </article>)}</div></section>)}
    </div>
  </div>;
}
