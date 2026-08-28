"use client";

import { BellRing, CalendarClock, Check, CheckSquare2, Clock3, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { KnowledgeShell, dateLabel, label } from "@/components/knowledge-shell";
import { Button } from "@/components/ui/button";
import { updateAction, updateDeadline, type ActionItem, type Deadline, type UpcomingSnapshot } from "@/lib/api/knowledge";

export function UpcomingWorkspace({ snapshot, pending }: { snapshot: UpcomingSnapshot; pending: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const sections: Array<[string, string, Deadline[], string]> = [
    ["Overdue", "Needs attention", snapshot.overdue, "border-red-200 bg-red-50/40"],
    ["Today", "Due today", snapshot.today, "border-amber-200 bg-amber-50/40"],
    ["Next 7 days", "Coming soon", snapshot.next_7_days, ""],
    ["Next 30 days", "Plan ahead", snapshot.next_30_days, ""],
    ["Future", "Later", snapshot.future, ""],
    ["Snoozed", "Temporarily hidden", snapshot.snoozed, "border-stone-200 bg-stone-50/50"],
  ];
  const empty = sections.every(([, , items]) => !items.length) && !snapshot.actions.length;
  async function deadlineAction(item: Deadline, action: "completed" | "dismissed" | "snoozed") {
    setBusy(`${item.id}:${action}`); setError("");
    try {
      let until: string | undefined;
      if (action === "snoozed") {
        const value = new Date();
        value.setDate(value.getDate() + 7);
        until = `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
      }
      await updateDeadline(item.id, action, until); router.refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update deadline"); }
    finally { setBusy(null); }
  }
  async function actionItem(item: ActionItem, action: "completed" | "dismissed") {
    setBusy(`${item.id}:${action}`); setError("");
    try { await updateAction(item.id, action); router.refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update action"); }
    finally { setBusy(null); }
  }
  return <KnowledgeShell eyebrow="Obligations" title="Upcoming" description="Reviewed, document-backed deadlines grouped by urgency. Reminders stay private inside PDI.">
    {snapshot.notifications.length ? <section className="mb-6 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-950"><BellRing className="size-4" />In-app reminders</div><div className="mt-3 flex flex-wrap gap-2">{snapshot.notifications.slice(0, 5).map((item) => { const evidence = item.evidence[0]; return <Link key={item.id} href={`/documents/${item.source_document_id}${evidence ? `?page=${evidence.page}` : ""}`} className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-xs text-emerald-900 hover:border-emerald-400"><span className="font-semibold">{label(item.kind)}</span> · {item.title}</Link>; })}</div></section> : null}
    {error ? <p role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
    {empty ? <div className="empty-state mb-8"><div><CalendarClock className="mx-auto size-8 text-stone-300" /><p className="mt-3 text-sm font-medium text-stone-700">No confirmed upcoming obligations</p><p className="mt-1 text-xs text-stone-400">PDI shows only obligations you have reviewed.</p>{pending ? <Link href="/review/knowledge" className="mt-4 inline-block text-sm font-medium text-emerald-800">Review suggestions ({pending}) →</Link> : null}</div></div> : null}
    <div className="grid gap-5 xl:grid-cols-2">{sections.map(([title, description, items, tone]) => items.length ? <DeadlineSection key={title} title={title} description={description} tone={tone} items={items} busy={busy} onAction={deadlineAction} /> : null)}</div>
    <section className="mt-7"><div className="mb-3 flex items-center gap-2"><span className="grid size-8 place-items-center rounded-lg bg-violet-50 text-violet-700"><CheckSquare2 className="size-4" /></span><div><h2 className="text-sm font-semibold text-stone-900">Action items</h2><p className="text-xs text-stone-400">Explicit tasks accepted from source documents</p></div></div><div className="panel divide-y divide-stone-100 overflow-hidden">{snapshot.actions.length ? snapshot.actions.map((item) => <ActionRow key={item.id} item={item} busy={busy} onAction={actionItem} />) : <p className="p-8 text-center text-sm text-stone-400">No confirmed open action items.</p>}</div></section>
    <p className="mt-5 text-xs leading-5 text-stone-400">Lead times are configurable by deadline type in Settings. PDI creates only one relevant in-app reminder per schedule and sends no email.</p>
  </KnowledgeShell>;
}

function DeadlineSection({ title, description, tone, items, busy, onAction }: { title: string; description: string; tone: string; items: Deadline[]; busy: string | null; onAction: (item: Deadline, action: "completed" | "dismissed" | "snoozed") => Promise<void> }) {
  return <section><div className="mb-3 flex items-center gap-2"><span className="grid size-8 place-items-center rounded-lg bg-emerald-50 text-emerald-800"><Clock3 className="size-4" /></span><div><h2 className="text-sm font-semibold text-stone-900">{title} <span className="ml-1 text-xs font-normal text-stone-400">{items.length}</span></h2><p className="text-xs text-stone-400">{description}</p></div></div><div className={`panel divide-y divide-stone-100 overflow-hidden ${tone}`}>{items.map((item) => <DeadlineRow key={item.id} item={item} busy={busy} onAction={onAction} />)}</div></section>;
}

function DeadlineRow({ item, busy, onAction }: { item: Deadline; busy: string | null; onAction: (item: Deadline, action: "completed" | "dismissed" | "snoozed") => Promise<void> }) {
  const evidence = item.evidence[0]; const source = `/documents/${item.source_document_id}${evidence ? `?page=${evidence.page}` : ""}`;
  return <article className="p-4"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><p className="break-words text-sm font-medium text-stone-800">{item.title}</p><p className="mt-1 text-xs text-stone-400">{label(item.deadline_type)} · {label(item.state)}{item.snoozed_until ? ` until ${dateLabel(item.snoozed_until)}` : ""}</p></div><time className="shrink-0 text-xs font-semibold tabular-nums text-stone-600">{dateLabel(item.due_at)}</time></div><div className="mt-3 flex flex-wrap items-center gap-2"><Button type="button" className="h-8 px-2.5 text-xs" disabled={busy !== null} onClick={() => void onAction(item, "completed")}><Check className="size-3.5" />Complete</Button><Button type="button" variant="secondary" className="h-8 px-2.5 text-xs" disabled={busy !== null} onClick={() => void onAction(item, "snoozed")}><Clock3 className="size-3.5" />Snooze 7 days</Button><button type="button" disabled={busy !== null} onClick={() => void onAction(item, "dismissed")} className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs text-stone-500 hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"><X className="size-3.5" />Dismiss</button><Link href={source} className="ml-auto inline-flex h-8 items-center gap-1 text-xs font-medium text-emerald-800 hover:underline">Evidence{evidence ? ` · page ${evidence.page}` : ""}<ExternalLink className="size-3" /></Link></div></article>;
}

function ActionRow({ item, busy, onAction }: { item: ActionItem; busy: string | null; onAction: (item: ActionItem, action: "completed" | "dismissed") => Promise<void> }) {
  const evidence = item.evidence[0]; const source = `/documents/${item.source_document_id}${evidence ? `?page=${evidence.page}` : ""}`;
  return <article className="p-4"><div className="flex items-start justify-between gap-4"><div><p className="text-sm font-medium text-stone-800">{item.title}</p><p className="mt-1 text-xs text-stone-400">{label(item.life_area)} · {label(item.priority)} priority</p></div><time className="text-xs font-semibold text-stone-600">{dateLabel(item.due_at)}</time></div><div className="mt-3 flex flex-wrap gap-2"><Button type="button" className="h-8 px-2.5 text-xs" disabled={busy !== null} onClick={() => void onAction(item, "completed")}><Check className="size-3.5" />Complete</Button><button type="button" disabled={busy !== null} onClick={() => void onAction(item, "dismissed")} className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs text-stone-500 hover:bg-red-50 hover:text-red-700 disabled:opacity-50"><X className="size-3.5" />Dismiss</button><Link href={source} className="ml-auto inline-flex h-8 items-center gap-1 text-xs font-medium text-emerald-800 hover:underline">Evidence{evidence ? ` · page ${evidence.page}` : ""}<ExternalLink className="size-3" /></Link></div></article>;
}
