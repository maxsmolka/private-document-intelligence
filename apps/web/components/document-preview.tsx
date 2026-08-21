"use client";

import { FileWarning, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { documentContentUrl } from "@/lib/api/documents";

export function DocumentPreview({
  documentId,
  mimeType,
  title,
  heightClass,
}: {
  documentId: string;
  mimeType: string;
  title: string;
  heightClass: string;
}) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const contentUrl = documentContentUrl(documentId);

  useEffect(() => {
    const controller = new AbortController();
    fetch(contentUrl, {
      credentials: "include",
      headers: { Range: "bytes=0-0" },
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Preview returned ${response.status}`);
        void response.body?.cancel();
        setState("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState("error");
      });
    return () => controller.abort();
  }, [attempt, contentUrl]);

  if (state === "loading") {
    return <div className={`grid place-items-center ${heightClass}`}><p className="text-sm text-stone-400">Loading protected preview…</p></div>;
  }
  if (state === "error") {
    return <div className={`grid place-items-center p-6 text-center ${heightClass}`}><div><FileWarning className="mx-auto size-8 text-amber-500" /><p className="mt-3 text-sm font-medium text-stone-800">Preview could not be loaded.</p><p className="mt-1 text-xs text-stone-500">The original document remains protected and unchanged.</p><button type="button" onClick={() => { setState("loading"); setAttempt((value) => value + 1); }} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 hover:bg-stone-50"><RotateCcw className="size-4" />Retry</button></div></div>;
  }
  if (mimeType.startsWith("image/")) {
    return <div className={`grid place-items-center p-5 ${heightClass}`}><img src={contentUrl} alt={`Preview of ${title}`} onError={() => setState("error")} className="max-h-[66vh] max-w-full rounded shadow-xl" /></div>;
  }
  return <iframe src={contentUrl} title={`Preview of ${title}`} className={`${heightClass} w-full border-0`} />;
}
