"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, Copy, Download, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { browserApiUrl } from "@/lib/api/documents";
import { securityRequest } from "@/lib/api/security";

type Step = "loading" | "welcome" | "admin" | "security" | "totp" | "recovery" | "ready";
type TotpSetup = { secret: string; qr_svg_base64: string; provisioning_uri: string; expires_at: string };

async function setupRequest<T>(path: string, options?: RequestInit): Promise<{ response: Response; body?: T; detail?: string }> {
  const response = await fetch(browserApiUrl(path), {
    ...options,
    credentials: "include",
    headers: { "content-type": "application/json", ...options?.headers },
  }).catch(() => null);
  if (!response) return { response: new Response(null, { status: 503 }), detail: "PDI setup is temporarily unavailable." };
  const body = await response.json().catch(() => ({})) as T & { detail?: string };
  return { response, body, detail: body.detail };
}

function Field({ label, name, type = "text", autoComplete, inputMode }: {
  label: string; name: string; type?: string; autoComplete?: string; inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
}) {
  return <label className="block text-sm font-medium text-stone-700">{label}<input className="field mt-1.5" name={name} type={type} required autoComplete={autoComplete} inputMode={inputMode} /></label>;
}

export function SetupWizard({ navigate }: { navigate: (destination: string) => void }) {
  const [step, setStep] = useState<Step>("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [totpAvailable, setTotpAvailable] = useState(false);
  const [totp, setTotp] = useState<TotpSetup | null>(null);
  const [codes, setCodes] = useState<string[]>([]);

  useEffect(() => {
    void setupRequest<{ setup_required: boolean }>("/api/v1/setup/status").then(({ response, body }) => {
      if (!response.ok) { setError("PDI setup status could not be loaded."); return; }
      if (!body?.setup_required) { navigate("/login"); return; }
      setStep("welcome");
    });
  }, [navigate]);

  async function createAdmin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const confirmation = String(data.get("confirmation") ?? "");
    if (password.length < 12) { setError("Password must contain at least 12 characters."); setBusy(false); return; }
    if (password !== confirmation) { setError("Password confirmation does not match."); setBusy(false); return; }
    const { response, body, detail } = await setupRequest<{ totp_available: boolean }>("/api/v1/setup/admin", {
      method: "POST",
      body: JSON.stringify({ username: data.get("username"), password, password_confirmation: confirmation }),
    });
    setBusy(false);
    if (response.status === 409) { navigate("/login"); return; }
    if (!response.ok) { setError(detail || "The administrator could not be created."); return; }
    setTotpAvailable(Boolean(body?.totp_available));
    form.reset();
    setStep("security");
  }

  async function startTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      setTotp(await securityRequest<TotpSetup>("/api/v1/account/2fa/setup", {
        method: "POST", body: JSON.stringify({ current_password: data.get("password") }),
      }));
      form.reset(); setStep("totp");
    } catch (value) { setError((value as Error).message); }
    setBusy(false);
  }

  async function enableTotp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const result = await securityRequest<{ recovery_codes: string[] }>("/api/v1/account/2fa/enable", {
        method: "POST", body: JSON.stringify({ current_password: data.get("password"), code: data.get("code") }),
      });
      setCodes(result.recovery_codes); form.reset(); setStep("recovery");
    } catch (value) { setError((value as Error).message); }
    setBusy(false);
  }

  function downloadCodes() {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([codes.join("\n") + "\n"], { type: "text/plain" }));
    link.download = "pdi-recovery-codes.txt"; link.click(); URL.revokeObjectURL(link.href);
  }

  return <main className="min-h-screen bg-[#f6f4ef] px-4 py-8 sm:grid sm:place-items-center">
    <section aria-live="polite" className="mx-auto w-full max-w-lg rounded-2xl border border-stone-200 bg-[#fbfaf7] p-6 shadow-xl shadow-stone-900/5 sm:p-8">
      <div className="flex items-center justify-between gap-4"><div className="grid size-10 place-items-center rounded-xl bg-stone-900 font-semibold text-white">P</div><span className="text-xs font-medium text-stone-500">First-run setup</span></div>
      {step === "loading" ? <><h1 className="mt-7 text-2xl font-semibold">Preparing PDI</h1><p className="mt-2 text-sm text-stone-500">Checking the secure setup state…</p></> : null}
      {step === "welcome" ? <><h1 className="mt-7 text-2xl font-semibold tracking-tight">Welcome to PDI</h1><p className="mt-2 text-sm leading-6 text-stone-600">Create the first administrator for this private document system. Setup closes permanently as soon as the account is created.</p><Button className="mt-7 w-full sm:w-auto" onClick={() => setStep("admin")}>Create the first administrator</Button></> : null}
      {step === "admin" ? <><h1 className="mt-7 text-2xl font-semibold tracking-tight">Administrator account</h1><p className="mt-2 text-sm text-stone-500">Use a unique password with at least 12 characters.</p><form onSubmit={createAdmin} className="mt-6 space-y-4"><Field label="Username" name="username" autoComplete="username" /><Field label="Password" name="password" type="password" autoComplete="new-password" /><Field label="Confirm password" name="confirmation" type="password" autoComplete="new-password" /><Button disabled={busy} className="w-full">{busy ? "Creating…" : "Create administrator"}</Button></form></> : null}
      {step === "security" ? <><div className="mt-7 flex items-center gap-3"><ShieldCheck className="size-6 text-emerald-800" /><h1 className="text-2xl font-semibold tracking-tight">Secure your account</h1></div><p className="mt-2 text-sm leading-6 text-stone-600">Two-factor authentication is optional and can also be configured later under Settings → Security.</p>{totpAvailable ? <form onSubmit={startTotp} className="mt-6 space-y-4"><Field label="Confirm your administrator password" name="password" type="password" autoComplete="current-password" /><Button disabled={busy} className="w-full">{busy ? "Preparing…" : "Set up authenticator"}</Button></form> : <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">TOTP is unavailable because the operator has not configured the server encryption key. Your administrator account is ready.</p>}<Button variant="secondary" className="mt-3 w-full" onClick={() => setStep("ready")}>Set up later</Button></> : null}
      {step === "totp" && totp ? <><h1 className="mt-7 text-2xl font-semibold tracking-tight">Add your authenticator</h1><p className="mt-2 text-sm text-stone-600">Scan the QR code or enter the manual secret, then verify a six-digit code.</p><img className="mx-auto mt-5 size-48 rounded-xl bg-white p-2" alt="PDI authenticator setup QR code" src={`data:image/svg+xml;base64,${totp.qr_svg_base64}`} /><p className="mt-4 text-xs text-stone-500">Manual secret — shown only during setup</p><code className="mt-1 block break-all rounded-lg bg-stone-100 p-3 text-xs">{totp.secret}</code><form onSubmit={enableTotp} className="mt-5 space-y-4"><Field label="Administrator password" name="password" type="password" autoComplete="current-password" /><Field label="6-digit authenticator code" name="code" autoComplete="one-time-code" inputMode="numeric" /><Button disabled={busy} className="w-full">{busy ? "Verifying…" : "Enable two-factor authentication"}</Button></form></> : null}
      {step === "recovery" ? <><div className="mt-7 flex items-center gap-3"><Check className="size-6 text-emerald-800" /><h1 className="text-2xl font-semibold tracking-tight">Save recovery codes</h1></div><p className="mt-2 text-sm text-stone-600">Each code works once. They will not be shown again.</p><div className="mt-5 grid grid-cols-1 gap-2 rounded-xl border border-amber-200 bg-amber-50 p-4 font-mono text-sm min-[380px]:grid-cols-2">{codes.map((code) => <code key={code}>{code}</code>)}</div><div className="mt-4 grid gap-2 sm:grid-cols-2"><Button variant="secondary" onClick={() => navigator.clipboard.writeText(codes.join("\n"))}><Copy className="size-4" />Copy</Button><Button variant="secondary" onClick={downloadCodes}><Download className="size-4" />Download</Button></div><Button className="mt-3 w-full" onClick={() => setStep("ready")}>I saved the recovery codes</Button></> : null}
      {step === "ready" ? <><div className="mt-7 grid size-12 place-items-center rounded-full bg-emerald-100 text-emerald-800"><Check className="size-6" /></div><h1 className="mt-5 text-2xl font-semibold tracking-tight">PDI is ready</h1><p className="mt-2 text-sm leading-6 text-stone-600">Your administrator account is active and this setup wizard is now permanently unavailable.</p><Button className="mt-7 w-full sm:w-auto" onClick={() => navigate("/")}>Continue to PDI</Button></> : null}
      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}
    </section>
  </main>;
}

export default function SetupPage() {
  return <SetupWizard navigate={(destination) => window.location.assign(destination)} />;
}
