"use client";

import { Check, Link2, Pencil, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { label } from "@/components/knowledge-shell";
import { acceptKnowledge, rejectKnowledge, type KnowledgeProposal } from "@/lib/api/knowledge";

function editableField(item: KnowledgeProposal) {
  if (item.proposal_type === "organization") return "canonical_name";
  if (item.proposal_type === "relationship") return "relationship_type";
  return "title";
}

function displayValue(item: KnowledgeProposal) {
  const field = editableField(item);
  return String(item.payload[field] ?? "Knowledge candidate");
}

export function KnowledgeReviewWorkspace({ proposals }: { proposals: KnowledgeProposal[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

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
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Review failed");
    } finally {
      setBusy(null);
    }
  }

  if (!proposals.length) {
    return <p className="py-16 text-center text-sm text-stone-400">No knowledge proposals await review.</p>;
  }
  return <div>
    {error ? <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
    <div className="divide-y divide-stone-200 border-y border-stone-200">
      {proposals.map((item) => <article key={item.id} className="py-5">
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
            </label> : <h2 className="mt-1 text-sm font-medium text-stone-900">{displayValue(item)}</h2>}
            <p className="mt-1 text-xs text-stone-400">{Math.round(item.confidence * 100)}% evidence strength{item.match_reason ? ` · ${item.match_reason}` : ""}</p>
          </div>
          <div className="flex gap-1">
            <button disabled={busy === item.id} onClick={() => decide(item, "create")} className="rounded-lg bg-stone-900 p-2 text-white" aria-label="Accept and create"><Check className="size-4" /></button>
            <button disabled={busy === item.id} onClick={() => setEditing(editing === item.id ? null : item.id)} className="rounded-lg border border-stone-200 p-2 text-stone-600" aria-label="Edit before accepting"><Pencil className="size-4" /></button>
            {item.possible_existing_organization_id ? <button disabled={busy === item.id} onClick={() => decide(item, "link")} className="rounded-lg border border-stone-200 p-2 text-stone-600" aria-label="Link existing organization"><Link2 className="size-4" /></button> : null}
            <button disabled={busy === item.id} onClick={() => decide(item, "reject")} className="rounded-lg border border-stone-200 p-2 text-stone-400" aria-label="Reject"><X className="size-4" /></button>
          </div>
        </div>
        {item.evidence.map((span, index) => <blockquote key={index} className="mt-3 border-l-2 border-amber-200 pl-3 text-sm text-stone-600">“{span.text}” <span className="text-xs text-stone-400">Page {span.page}</span></blockquote>)}
        {item.validation_notes.length ? <p className="mt-3 text-xs text-stone-400">Validation: {item.validation_notes.map(label).join(" · ")}</p> : null}
      </article>)}
    </div>
  </div>;
}
