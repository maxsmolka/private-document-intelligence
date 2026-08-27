"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, History, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { securityRequest } from "@/lib/api/security";

type Release = {
  version: string; release_commit: string; published_at: string; release_notes: string;
  release_notes_url: string; migration_required: boolean; reindex_required: boolean;
  backup_required: boolean; rollback_mode: string; backend_digest: string; web_digest: string;
  target_schema: string;
};
type Run = {
  id: string; state: string; from_version: string; to_version: string; compatibility: string;
  migration_required: boolean; reindex_required: boolean; backup_required: boolean;
  backup_verified: boolean; rollback_mode: string; expected_downtime: string;
  schema_before: string | null; schema_target: string; target_backend_digest: string;
  target_web_digest: string; warnings: string[]; preflight: {
    result?: string; checks?: Record<string, string>; blockers?: string[]; active_jobs?: number;
    queued_jobs?: number; resource_leases?: number;
  }; failure_code: string | null; failure_message: string | null; operator_command: string | null;
  started_at: string; finished_at: string | null;
};
type Status = {
  current_version: string; update_channel: string; available_release: Release | null;
  update_available: boolean; active_run: Run | null; last_successful_check: string | null;
  last_successful_update: string | null; installation_mode: string; automatic_installation: boolean;
};

function Flag({ label, value }: { label: string; value: boolean }) {
  return <div className="min-w-0"><dt className="text-xs text-stone-500">{label}</dt><dd className="mt-0.5 text-sm font-medium">{value ? "Required" : "Not required"}</dd></div>;
}

export function UpdateManager() {
  const [status, setStatus] = useState<Status | null>(null);
  const [history, setHistory] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", success: "" });
  const load = useCallback(() => Promise.all([
        securityRequest<Status>("/api/v1/system/update"),
        securityRequest<Run[]>("/api/v1/system/update/history"),
      ]).then(([next, runs]) => { setStatus(next); setHistory(runs); })
        .catch((error: Error) => { setMessage({ error: error.message, success: "" }); }), []);
  useEffect(() => { void load(); }, [load]);

  async function action(path: string, success: string) {
    setBusy(true); setMessage({ error: "", success: "" });
    try {
      await securityRequest(path, { method: "POST" });
      await load(); setMessage({ error: "", success });
    } catch (error) { setMessage({ error: (error as Error).message, success: "" }); }
    finally { setBusy(false); }
  }

  const release = status?.available_release;
  const run = status?.active_run;
  async function prepare() {
    if (!run || !window.confirm(`Prepare PDI ${run.from_version} → ${run.to_version}? This enables maintenance mode, drains active jobs, and creates a verified backup. Host deployment still requires the operator CLI.`)) return;
    await action(`/api/v1/system/update/runs/${run.id}/prepare`, "Update is prepared for constrained host-side execution.");
  }
  return <div className="page">
    <p className="eyebrow">Settings</p><h1 className="page-title mt-1">Updates</h1>
    <p className="page-description">Review verified releases and prepare a controlled, backup-protected update.</p>
    {message.error ? <p role="alert" className="mt-4 text-sm text-red-700">{message.error}</p> : null}
    {message.success ? <p role="status" className="mt-4 text-sm text-emerald-800">{message.success}</p> : null}
    <section className="panel mt-6 max-w-4xl p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs text-stone-500">Current version</p><p className="mt-1 text-2xl font-semibold tracking-tight">PDI {status?.current_version ?? "…"}</p><p className="mt-1 text-xs text-stone-500">Channel: {status?.update_channel ?? "…"} · Installation: operator controlled</p></div>
        <Button variant="secondary" disabled={busy} onClick={() => action("/api/v1/system/update/check", "Official release metadata refreshed.")}><RefreshCw className={`size-4 ${busy ? "animate-spin" : ""}`} />Check for updates</Button>
      </div>
      {!release && status ? <div className="mt-5 flex items-center gap-2 rounded-xl bg-stone-50 p-4 text-sm text-stone-700"><CheckCircle2 className="size-4 text-emerald-700" />No verified newer release is cached.</div> : null}
      {release ? <div className="mt-5 border-t border-stone-100 pt-5">
        <div className="flex items-center gap-2"><Download className="size-5 text-emerald-800" /><h2 className="font-medium">PDI {release.version} available</h2></div>
        <p className="mt-1 text-xs text-stone-500">Published {new Date(release.published_at).toLocaleString()} · commit {release.release_commit.slice(0, 12)}</p>
        <dl className="mt-5 grid gap-4 sm:grid-cols-4"><Flag label="Migration" value={release.migration_required} /><Flag label="Backup" value={release.backup_required} /><Flag label="Reindex" value={release.reindex_required} /><div><dt className="text-xs text-stone-500">Rollback</dt><dd className="mt-0.5 text-sm font-medium">{release.rollback_mode === "restore_backup" ? "Restore backup" : "Previous images"}</dd></div></dl>
        <details className="mt-5 rounded-xl border border-stone-200 p-4"><summary className="cursor-pointer text-sm font-medium">Release notes</summary><div className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap text-sm leading-6 text-stone-600">{release.release_notes || "No release notes supplied."}</div></details>
        {!run ? <Button className="mt-5" disabled={busy} onClick={() => action("/api/v1/system/update/plan", "Deterministic update plan created.")}><ShieldCheck className="size-4" />Review update plan</Button> : null}
      </div> : null}
    </section>
    {run ? <section className="panel mt-5 max-w-4xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow">Active update run</p><h2 className="mt-1 text-lg font-semibold">{run.from_version} → {run.to_version}</h2></div><span className={`status-pill ${run.compatibility === "compatible" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-800"}`}>{run.state.replaceAll("_", " ")}</span></div>
      <dl className="mt-5 grid min-w-0 gap-4 sm:grid-cols-3"><div className="min-w-0"><dt className="text-xs text-stone-500">Schema</dt><dd className="mt-0.5 break-all text-sm">{run.schema_before} → {run.schema_target}</dd></div><Flag label="Migration" value={run.migration_required} /><Flag label="Backup" value={run.backup_required} /><div className="min-w-0"><dt className="text-xs text-stone-500">Expected downtime</dt><dd className="mt-0.5 text-sm capitalize">{run.expected_downtime}</dd></div><div className="min-w-0"><dt className="text-xs text-stone-500">Backend digest</dt><dd className="mt-0.5 truncate font-mono text-xs">{run.target_backend_digest}</dd></div><div className="min-w-0"><dt className="text-xs text-stone-500">Web digest</dt><dd className="mt-0.5 truncate font-mono text-xs">{run.target_web_digest}</dd></div></dl>
      {run.warnings.length ? <div className="mt-5 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><AlertTriangle className="mt-0.5 size-4 shrink-0" /><div>{run.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div></div> : null}
      {run.preflight.result ? <div className="mt-5 rounded-xl border border-stone-200 p-4"><p className="text-sm font-medium">Preflight: {run.preflight.result}</p><p className="mt-1 text-xs text-stone-500">Active jobs {run.preflight.active_jobs} · Queued jobs {run.preflight.queued_jobs} · Resource leases {run.preflight.resource_leases}</p></div> : null}
      {run.state === "planned" ? <Button className="mt-5" disabled={busy || run.compatibility !== "compatible"} onClick={prepare}>Prepare and verify backup</Button> : null}
      {run.state === "awaiting_execution" ? <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"><p className="font-medium">Prepared safely</p><p className="mt-1">The verified backup is tied to this run. Run the documented host-side command with the NAS Compose and managed-overlay paths. The web application has no Docker access.</p><code className="mt-3 block break-all whitespace-pre-wrap rounded-lg bg-white p-3 text-xs">{run.operator_command}</code></div> : null}
      {run.failure_code ? <div role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900"><p className="font-medium">{run.failure_code}</p><p>{run.failure_message}</p></div> : null}
      {run.state === "rollback_required" ? <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"><p className="font-medium">Operator rollback required</p><p className="mt-1">Keep writers stopped. Restore the verified backup linked to this run, restore the previous exact backend and web digests, then start the previous release and repeat readiness, search, and storage verification. Do not run a general Alembic downgrade.</p></div> : null}
    </section> : null}
    <section className="panel mt-5 max-w-4xl overflow-hidden"><div className="flex items-center gap-2 border-b border-stone-100 p-4"><History className="size-4 text-stone-500" /><h2 className="text-sm font-medium">Update history</h2></div>{history.length ? <div className="divide-y divide-stone-100">{history.map((item) => <div key={item.id} className="flex flex-wrap items-center gap-3 p-4 text-sm"><span className="min-w-40 font-medium">{item.from_version} → {item.to_version}</span><span className="status-pill border-stone-200">{item.state.replaceAll("_", " ")}</span><span className="ml-auto text-xs text-stone-500">{new Date(item.started_at).toLocaleString()}</span></div>)}</div> : <p className="p-5 text-sm text-stone-500">No update runs recorded.</p>}</section>
  </div>;
}
