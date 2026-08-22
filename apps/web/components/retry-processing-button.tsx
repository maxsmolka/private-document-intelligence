"use client";

import { RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { getReviewDetailClient, retryDocument } from "@/lib/api/documents";

type RetryState = "idle" | "accepted" | "processing" | "ready" | "failed";

function pause(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function RetryProcessingButton({ documentId }: { documentId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [state, setState] = useState<RetryState>("idle");

  async function retry() {
    setBusy(true);
    setError("");
    setState("accepted");
    try {
      const accepted = await retryDocument(documentId);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await pause(1000);
        const detail = await getReviewDetailClient(documentId);
        const job = detail.latest_job;
        if (job?.id !== accepted.id) continue;
        if (job.state === "failed") {
          setState("failed");
          setError(job.last_error ?? "Processing failed. The original document is unchanged.");
          setBusy(false);
          router.refresh();
          return;
        }
        if (job.state === "completed") {
          setState("ready");
          setBusy(false);
          router.refresh();
          return;
        }
        setState("processing");
      }
      setState("processing");
      setError("Processing is still running. This page will show the latest state when refreshed.");
      setBusy(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry processing");
      setState("failed");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
      <Button type="button" variant="secondary" onClick={retry} disabled={busy}>
        <RotateCcw className="size-4" />
        {state === "accepted" ? "Retry accepted…" : state === "processing" ? "Processing…" : "Retry processing"}
      </Button>
      {state === "ready" ? <span role="status" className="text-xs font-medium text-emerald-700">Ready for review</span> : null}
      </div>
      <p className="max-w-sm text-[11px] leading-4 text-stone-500">Re-runs document extraction, OCR when needed, and intelligence analysis. The original file is not changed.</p>
      {error ? <p role="alert" className={state === "processing" ? "text-xs text-amber-700" : "text-xs text-red-600"}>{error}</p> : null}
    </div>
  );
}
