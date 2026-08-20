"use client";

import { RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { retryDocument } from "@/lib/api/documents";

export function RetryProcessingButton({ documentId }: { documentId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function retry() {
    setBusy(true);
    setError("");
    try {
      await retryDocument(documentId);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not retry processing");
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button type="button" variant="secondary" onClick={retry} disabled={busy}>
        <RotateCcw className="size-4" />
        {busy ? "Queuing…" : "Retry processing"}
      </Button>
      {error ? <span className="text-xs text-red-600">{error}</span> : null}
    </div>
  );
}
