"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Progress from "@radix-ui/react-progress";
import { Check, FileUp, Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { DragEvent, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { DocumentRecord, DocumentUploadResult } from "@/lib/api/documents";
import { browserApiUrl } from "@/lib/api/documents";

type UploadState = "idle" | "uploading" | "success" | "duplicate" | "error";
const ACCEPTED = ["application/pdf", "image/jpeg", "image/png"];

export function UploadDialog() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [filename, setFilename] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<DocumentRecord | null>(null);

  function reset() {
    setState("idle"); setProgress(0); setFilename(""); setError(""); setResult(null); setDragging(false);
  }

  function upload(file: File) {
    if (!ACCEPTED.includes(file.type)) {
      setState("error"); setError("Choose a PDF, JPEG, or PNG file."); return;
    }
    setFilename(file.name); setState("uploading"); setProgress(0); setError("");
    const body = new FormData(); body.append("file", file);
    const request = new XMLHttpRequest();
    request.open("POST", browserApiUrl("/api/v1/documents"));
    request.withCredentials = true;
    const csrf = document.cookie.split("; ").find((value) => value.startsWith("pdi_csrf="))?.split("=")[1];
    if (csrf) request.setRequestHeader("x-csrf-token", decodeURIComponent(csrf));
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) {
        const payload = JSON.parse(request.responseText) as DocumentUploadResult;
        setProgress(100); setResult(payload.document);
        if (payload.duplicate) {
          setState("duplicate");
        } else {
          setState("success");
          window.setTimeout(() => router.push(`/documents/${payload.document.id}`), 500);
        }
      } else {
        let message = "The document could not be uploaded.";
        try { message = (JSON.parse(request.responseText) as { detail?: string }).detail ?? message; } catch { /* use default */ }
        setState("error"); setError(message);
      }
    });
    request.addEventListener("error", () => { setState("error"); setError("The API could not be reached."); });
    request.send(body);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files[0]; if (file) upload(file);
  }

  return (
    <Dialog.Root open={open} onOpenChange={(value) => { setOpen(value); if (!value) reset(); }}>
      <Dialog.Trigger asChild><Button><Plus className="size-4" />Add document</Button></Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-stone-950/25 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-stone-200 bg-[#fbfaf7] p-6 shadow-2xl shadow-stone-950/15 focus:outline-none">
          <div className="flex items-start justify-between"><div><Dialog.Title className="text-lg font-semibold tracking-tight text-stone-950">Add a document</Dialog.Title><Dialog.Description className="mt-1 text-sm text-stone-500">PDF, JPEG, or PNG. Your file is stored locally.</Dialog.Description></div><Dialog.Close className="rounded-md p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700" aria-label="Close"><X className="size-4" /></Dialog.Close></div>
          <input ref={input} type="file" className="hidden" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload(file); }} />
          <div
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`mt-6 grid min-h-56 place-items-center rounded-xl border border-dashed p-8 text-center transition ${dragging ? "border-stone-500 bg-stone-100" : "border-stone-300 bg-white/60"}`}
          >
            {state === "idle" && <div><span className="mx-auto mb-4 grid size-11 place-items-center rounded-xl border border-stone-200 bg-white shadow-sm"><FileUp className="size-5 text-stone-600" /></span><p className="text-sm font-medium text-stone-800">Drop a document here</p><p className="mt-1 text-xs text-stone-500">or choose one from your computer</p><Button variant="secondary" className="mt-5" onClick={() => input.current?.click()}>Choose file</Button></div>}
            {state === "uploading" && <div className="w-full max-w-xs"><FileUp className="mx-auto size-6 text-stone-500" /><p className="mt-3 truncate text-sm font-medium text-stone-800">{filename}</p><Progress.Root value={progress} className="mt-5 h-1.5 overflow-hidden rounded-full bg-stone-200"><Progress.Indicator className="h-full bg-stone-800 transition-transform" style={{ transform: `translateX(-${100 - progress}%)` }} /></Progress.Root><p className="mt-2 text-xs tabular-nums text-stone-500">Uploading {progress}%</p></div>}
            {state === "success" && <div><span className="mx-auto grid size-11 place-items-center rounded-full bg-emerald-100 text-emerald-700"><Check className="size-5" /></span><p className="mt-3 text-sm font-medium text-stone-800">Document added</p><p className="mt-1 text-xs text-stone-500">Opening document…</p></div>}
            {state === "duplicate" && result ? <div><span className="mx-auto grid size-11 place-items-center rounded-full bg-amber-100 text-amber-700"><Check className="size-5" /></span><p className="mt-3 text-sm font-semibold text-stone-900">Document already exists</p><p className="mt-2 text-xs leading-5 text-stone-600">This file is identical to an existing document.<br />No duplicate was created.</p><p className="mt-2 text-[11px] text-stone-400">Originally added: {new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Berlin" }).format(new Date(result.created_at))}</p><Button className="mt-5" onClick={() => router.push(`/documents/${result.id}`)}>Open existing document</Button></div> : null}
            {state === "error" && <div><span className="mx-auto grid size-11 place-items-center rounded-full bg-red-50 text-red-600"><X className="size-5" /></span><p className="mt-3 text-sm font-medium text-stone-800">Upload failed</p><p className="mt-1 text-xs leading-5 text-red-600">{error}</p><Button variant="secondary" className="mt-5" onClick={reset}>Try again</Button></div>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
