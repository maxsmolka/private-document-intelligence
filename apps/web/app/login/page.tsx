"use client";

import { FormEvent, useState } from "react";
import { publicApiUrl } from "@/lib/api/documents";

export default function LoginPage() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const response = await fetch(`${publicApiUrl()}/api/v1/auth/login`, {
      method: "POST", credentials: "include", headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
    }).catch(() => null);
    if (!response?.ok) {
      setError(response?.status === 429 ? "Too many attempts. Try again later." : "Invalid username or password.");
      setBusy(false); return;
    }
    const next = new URLSearchParams(window.location.search).get("next") || "/";
    window.location.assign(next.startsWith("/") ? next : "/");
  }
  return <div className="fixed inset-0 z-50 grid place-items-center bg-[#f6f4ef] px-5">
    <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-stone-200 bg-[#fbfaf7] p-7 shadow-xl shadow-stone-900/5">
      <div className="grid size-10 place-items-center rounded-xl bg-stone-900 font-semibold text-white">P</div>
      <h1 className="mt-6 text-xl font-semibold tracking-tight text-stone-950">Sign in to PDI</h1>
      <p className="mt-1 text-sm text-stone-500">Access your private document system.</p>
      <label className="mt-6 block text-xs font-medium text-stone-600">Username<input name="username" required autoComplete="username" className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-stone-200" /></label>
      <label className="mt-4 block text-xs font-medium text-stone-600">Password<input name="password" required type="password" autoComplete="current-password" className="mt-1.5 w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-stone-200" /></label>
      {error ? <p role="alert" className="mt-4 text-sm text-red-600">{error}</p> : null}
      <button disabled={busy} className="mt-6 w-full rounded-lg bg-stone-900 py-2.5 text-sm font-medium text-white disabled:opacity-50">{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  </div>;
}
