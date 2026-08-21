"use client";

import { RotateCcw } from "lucide-react";

export default function ErrorPage() {
  return <div className="mx-auto max-w-xl px-5 py-20 text-center"><h1 className="text-2xl font-semibold text-stone-900">PDI could not load this view.</h1><p className="mt-3 text-sm text-stone-500">Your documents are unaffected. Check that the local services are available, then retry.</p><button type="button" onClick={() => window.location.reload()} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-stone-900 px-4 py-2.5 text-sm font-medium text-white"><RotateCcw className="size-4" />Retry</button></div>;
}
