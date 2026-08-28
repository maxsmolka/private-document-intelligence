"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, FolderInput, Mail, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { securityRequest } from "@/lib/api/security";

type Health = "unknown" | "healthy" | "degraded" | "disabled";

export type IngestionSource = {
  id: string;
  source_type: "consume" | "mail";
  display_name: string;
  enabled: boolean;
  health: Health;
  safe_configuration: Record<string, unknown>;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
  last_report: Record<string, unknown>;
  ingested_document_count: number;
  pending_work: number;
  pending_failures: number;
  retry_supported: boolean;
};

const healthStyle: Record<Health, string> = {
  healthy: "border-emerald-200 bg-emerald-50 text-emerald-800",
  degraded: "border-red-200 bg-red-50 text-red-800",
  disabled: "border-stone-200 bg-stone-50 text-stone-600",
  unknown: "border-amber-200 bg-amber-50 text-amber-800",
};

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

function label(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
}

function displayValue(value: unknown) {
  if (value === null || value === "") return "Not configured";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function IngestionSourcesPanel() {
  const [sources, setSources] = useState<IngestionSource[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState({ error: "", success: "" });

  const load = useCallback(async () => {
    try {
      setSources(await securityRequest<IngestionSource[]>("/api/v1/ingestion/sources"));
      setMessage((current) => ({ ...current, error: "" }));
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    securityRequest<IngestionSource[]>("/api/v1/ingestion/sources")
      .then((items) => {
        if (active) setSources(items);
      })
      .catch((error: Error) => {
        if (active) setMessage({ error: error.message, success: "" });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  async function toggle(source: IngestionSource) {
    setBusy(source.id);
    setMessage({ error: "", success: "" });
    try {
      const updated = await securityRequest<IngestionSource>(
        `/api/v1/ingestion/sources/${source.id}/enabled`,
        { method: "POST", body: JSON.stringify({ enabled: !source.enabled }) },
      );
      setSources((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage({ error: "", success: `${source.display_name} ${updated.enabled ? "enabled" : "disabled"}.` });
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    } finally {
      setBusy(null);
    }
  }

  async function retry(source: IngestionSource) {
    setBusy(source.id);
    setMessage({ error: "", success: "" });
    try {
      const result = await securityRequest<{ requested: number }>(
        `/api/v1/ingestion/sources/${source.id}/retry`,
        { method: "POST" },
      );
      await load();
      setMessage({ error: "", success: `${result.requested} failed item${result.requested === 1 ? "" : "s"} queued for retry.` });
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    } finally {
      setBusy(null);
    }
  }

  return <div className="page">
    <p className="eyebrow">Settings</p>
    <div className="mt-1 flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="page-title">Ingestion</h1><p className="page-description">Monitor and control scanner-folder and read-only mailbox sources.</p></div>
      <Button variant="secondary" disabled={loading || busy !== null} onClick={() => { setLoading(true); void load(); }}><RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
    </div>
    {message.error ? <p role="alert" className="mt-4 text-sm text-red-700">{message.error}</p> : null}
    {message.success ? <p role="status" className="mt-4 text-sm text-emerald-800">{message.success}</p> : null}
    {loading && !sources.length ? <div className="panel mt-6 max-w-5xl p-5 text-sm text-stone-500">Loading ingestion sources…</div> : null}
    <div className="mt-6 grid max-w-5xl gap-5 xl:grid-cols-2">
      {sources.map((source) => {
        const Icon = source.source_type === "consume" ? FolderInput : Mail;
        return <section key={source.id} className="panel min-w-0 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-stone-100 text-stone-600"><Icon className="size-5" /></span><div className="min-w-0"><h2 className="font-semibold text-stone-950">{source.display_name}</h2><p className="text-xs text-stone-500">{source.source_type === "consume" ? "Scanner and watched folder" : "TLS mailbox · read-only"}</p></div></div>
            <span className={`status-pill capitalize ${healthStyle[source.health]}`}>{source.health}</span>
          </div>
          {source.health === "degraded" ? <div className="mt-4 flex gap-2 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-800"><AlertTriangle className="mt-0.5 size-4 shrink-0" /><span>Attention required{source.last_error ? ` · ${source.last_error}` : ""}</span></div> : null}
          {source.health === "healthy" ? <div className="mt-4 flex items-center gap-2 text-xs text-emerald-800"><CheckCircle2 className="size-4" />Latest source check completed successfully.</div> : null}
          <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-xs text-stone-500">Last check</dt><dd className="mt-0.5">{dateTime(source.last_checked_at)}</dd></div>
            <div><dt className="text-xs text-stone-500">Last success</dt><dd className="mt-0.5">{dateTime(source.last_success_at)}</dd></div>
            <div><dt className="text-xs text-stone-500">Documents</dt><dd className="mt-0.5 text-lg font-semibold">{source.ingested_document_count}</dd></div>
            <div><dt className="text-xs text-stone-500">Pending work</dt><dd className="mt-0.5 text-lg font-semibold">{source.pending_work}</dd></div>
            <div><dt className="text-xs text-stone-500">Pending failures</dt><dd className={`mt-0.5 text-lg font-semibold ${source.pending_failures ? "text-red-700" : ""}`}>{source.pending_failures}</dd></div>
            <div><dt className="text-xs text-stone-500">Last failure</dt><dd className="mt-0.5">{dateTime(source.last_failure_at)}</dd></div>
          </dl>
          <details className="mt-5 rounded-xl border border-stone-200 p-4"><summary className="cursor-pointer text-sm font-medium">Safe configuration</summary><dl className="mt-3 grid gap-3 sm:grid-cols-2">{Object.entries(source.safe_configuration).map(([key, value]) => <div className="min-w-0" key={key}><dt className="text-[11px] text-stone-500">{label(key)}</dt><dd className="mt-0.5 break-words text-xs text-stone-800">{displayValue(value)}</dd></div>)}</dl></details>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="secondary" disabled={busy === source.id} onClick={() => void toggle(source)}>{source.enabled ? "Disable source" : "Enable source"}</Button>
            {source.retry_supported ? <Button disabled={!source.enabled || source.pending_failures === 0 || busy === source.id} onClick={() => void retry(source)}>Retry failures</Button> : null}
          </div>
        </section>;
      })}
    </div>
    <p className="mt-5 max-w-5xl text-xs leading-5 text-stone-500">Credentials and deployment-owned secrets are never shown here. Mail ingestion does not delete, move, or mark messages.</p>
  </div>;
}
