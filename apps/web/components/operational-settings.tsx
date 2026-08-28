"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, RotateCcw, Save, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { securityRequest } from "@/lib/api/security";

type Setting = {
  key: string;
  label: string;
  description: string;
  classification: "A" | "B";
  value: unknown;
  default_value: unknown;
  source: "deployment" | "runtime";
  requires_restart: boolean;
  input_kind: "boolean" | "integer" | "number" | "text" | "select" | "resource_limits";
  minimum: number | null;
  maximum: number | null;
  options: string[];
  updated_at: string | null;
};

type Domain = { key: string; settings: Setting[] };
type SettingsResponse = { domains: Domain[]; restart_required: boolean };

const domainLabels: Record<string, string> = {
  general: "General",
  documents: "Documents",
  ocr: "OCR",
  intelligence: "Intelligence",
  ingestion: "Ingestion",
  search: "Search",
  execution: "Execution",
  backup: "Backup",
  updates: "Updates",
  notifications: "Notifications",
  security: "Security",
  system: "System",
};

const emptyDescriptions: Record<string, string> = {
  search: "PostgreSQL full-text search is authoritative and currently has no useful runtime controls.",
  backup: "Backup destinations remain deployment-owned. Coordinated backup actions are available to operators without exposing host paths.",
  notifications: "Private in-app reminder policy appears here. External delivery remains disabled.",
  system: "Database, storage, network, build, and secret settings remain deployment-owned and are intentionally read-only.",
};

function toInputValue(value: unknown) {
  return value === null || value === undefined ? "" : String(value);
}

function SettingControl({ setting, value, onChange }: {
  setting: Setting;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const id = `setting-${setting.key}`;
  if (setting.input_kind === "boolean") {
    return <label htmlFor={id} className="flex cursor-pointer items-center gap-3 rounded-xl border border-stone-200 bg-stone-50 px-4 py-3">
      <input id={id} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
      <span className="text-sm font-medium">{Boolean(value) ? "Enabled" : "Disabled"}</span>
    </label>;
  }
  if (setting.input_kind === "select") {
    return <select id={id} className="field" value={toInputValue(value)} onChange={(event) => onChange(event.target.value)}>
      {setting.options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>;
  }
  if (setting.input_kind === "resource_limits") {
    const limits = value as Record<string, number>;
    return <div className="grid gap-3 sm:grid-cols-2">
      {Object.entries(limits).map(([key, limit]) => <label key={key} className="text-xs font-medium text-stone-600">{key.replaceAll("_", " ")}
        <input className="field mt-1.5" type="number" min={1} max={64} value={limit} onChange={(event) => onChange({ ...limits, [key]: Number(event.target.value) })} />
      </label>)}
    </div>;
  }
  return <input
    id={id}
    className="field"
    type={setting.input_kind === "text" ? "text" : "number"}
    step={setting.input_kind === "number" ? "any" : "1"}
    min={setting.minimum ?? undefined}
    max={setting.maximum ?? undefined}
    value={toInputValue(value)}
    onChange={(event) => onChange(setting.input_kind === "text" ? event.target.value : Number(event.target.value))}
  />;
}

export function OperationalSettingsPanel() {
  const [response, setResponse] = useState<SettingsResponse | null>(null);
  const [selected, setSelected] = useState("general");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ error: "", success: "" });

  const load = useCallback(async () => {
    try {
      const payload = await securityRequest<SettingsResponse>("/api/v1/admin/settings");
      setResponse(payload);
      setDraft(Object.fromEntries(payload.domains.flatMap((domain) => domain.settings.map((setting) => [setting.key, setting.value]))));
      setMessage((current) => ({ ...current, error: "" }));
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    }
  }, []);

  useEffect(() => {
    let active = true;
    securityRequest<SettingsResponse>("/api/v1/admin/settings")
      .then((payload) => {
        if (!active) return;
        setResponse(payload);
        setDraft(Object.fromEntries(payload.domains.flatMap((item) => item.settings.map((setting) => [setting.key, setting.value]))));
      })
      .catch((error: Error) => {
        if (active) setMessage({ error: error.message, success: "" });
      });
    return () => { active = false; };
  }, []);
  const domain = useMemo(() => response?.domains.find((item) => item.key === selected), [response, selected]);
  const changed = domain?.settings.some((setting) => JSON.stringify(draft[setting.key]) !== JSON.stringify(setting.value)) ?? false;

  async function save() {
    if (!domain) return;
    setBusy(true);
    setMessage({ error: "", success: "" });
    try {
      const values = Object.fromEntries(domain.settings.filter((setting) => JSON.stringify(draft[setting.key]) !== JSON.stringify(setting.value)).map((setting) => [setting.key, draft[setting.key]]));
      const result = await securityRequest<{ changed: string[]; restart_required: boolean }>(`/api/v1/admin/settings/${domain.key}`, { method: "PUT", body: JSON.stringify({ values }) });
      await load();
      setMessage({ error: "", success: `${result.changed.length} setting${result.changed.length === 1 ? "" : "s"} saved.${result.restart_required ? " Restart PDI to apply the marked setting." : " New work uses the updated policy immediately."}` });
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!domain || !window.confirm(`Reset ${domainLabels[domain.key]} settings to deployment-safe defaults?`)) return;
    setBusy(true);
    setMessage({ error: "", success: "" });
    try {
      await securityRequest(`/api/v1/admin/settings/${domain.key}/reset`, { method: "POST" });
      await load();
      setMessage({ error: "", success: `${domainLabels[domain.key]} settings reset to deployment-safe defaults.` });
    } catch (error) {
      setMessage({ error: (error as Error).message, success: "" });
    } finally {
      setBusy(false);
    }
  }

  return <div className="page">
    <p className="eyebrow">Settings</p>
    <h1 className="page-title mt-1">Administration</h1>
    <p className="page-description">Operator-safe runtime policy. Deployment configuration and secrets stay outside the browser.</p>
    {response?.restart_required ? <div role="status" className="mt-5 flex max-w-5xl gap-2 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><AlertTriangle className="mt-0.5 size-4 shrink-0" />A saved setting marked “restart required” is active in durable policy and will fully apply after PDI restarts.</div> : null}
    {message.error ? <p role="alert" className="mt-4 text-sm text-red-700">{message.error}</p> : null}
    {message.success ? <p role="status" className="mt-4 text-sm text-emerald-800">{message.success}</p> : null}
    <div className="mt-6 grid max-w-6xl gap-5 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label="Settings domains" className="panel flex gap-1 overflow-x-auto p-2 lg:block lg:space-y-1 lg:self-start">
        {(response?.domains ?? []).map((item) => <button key={item.key} type="button" onClick={() => setSelected(item.key)} className={`shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium transition lg:block lg:w-full ${selected === item.key ? "bg-emerald-900 text-white" : "text-stone-600 hover:bg-stone-100 hover:text-stone-950"}`}>{domainLabels[item.key]}</button>)}
      </nav>
      <section className="panel min-w-0 p-5 sm:p-6">
        {!response ? <p className="text-sm text-stone-500">Loading administration settings…</p> : null}
        {domain ? <>
          <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-stone-950">{domainLabels[domain.key]}</h2><p className="mt-1 text-sm text-stone-500">Only validated operational policy is editable here.</p></div><Settings2 className="size-5 text-stone-400" /></div>
          {!domain.settings.length ? <div className="mt-5 rounded-xl border border-stone-200 bg-stone-50 p-4 text-sm leading-6 text-stone-600">{emptyDescriptions[domain.key] ?? "No runtime controls are applicable."}</div> : <div className="mt-6 divide-y divide-stone-100">{domain.settings.map((setting) => <div key={setting.key} className="grid gap-3 py-5 first:pt-0 md:grid-cols-[minmax(0,1fr)_minmax(14rem,20rem)] md:items-start md:gap-8"><div><label htmlFor={`setting-${setting.key}`} className="text-sm font-medium text-stone-900">{setting.label}</label><p className="mt-1 text-xs leading-5 text-stone-500">{setting.description}</p><div className="mt-2 flex flex-wrap gap-2"><span className="status-pill border-stone-200 bg-stone-50 text-stone-600">{setting.source === "runtime" ? "Admin override" : "Deployment default"}</span>{setting.requires_restart ? <span className="status-pill border-amber-200 bg-amber-50 text-amber-800">Restart required</span> : <span className="status-pill border-emerald-200 bg-emerald-50 text-emerald-800">Applies to new work</span>}</div></div><SettingControl setting={setting} value={draft[setting.key]} onChange={(value) => setDraft((current) => ({ ...current, [setting.key]: value }))} /></div>)}</div>}
          {domain.settings.length ? <div className="mt-5 flex flex-wrap gap-2 border-t border-stone-100 pt-5"><Button disabled={!changed || busy} onClick={() => void save()}><Save className="size-4" />Save changes</Button><Button variant="secondary" disabled={busy || !domain.settings.some((setting) => setting.source === "runtime")} onClick={() => void reset()}><RotateCcw className="size-4" />Reset to safe defaults</Button></div> : null}
        </> : null}
      </section>
    </div>
  </div>;
}
