"use client";

import { ChevronLeft, ChevronRight, Download, Expand, FileWarning, Maximize2, Minus, Plus, RotateCcw } from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useCallback, useEffect, useRef, useState } from "react";
import { documentContentUrl } from "@/lib/api/documents";

type FitMode = "width" | "page" | "custom";
type PdfState = "loading" | "rendering" | "rendered" | "error" | "unsupported";

export function DocumentPreview({ documentId, mimeType, title, heightClass, initialPage = 1 }: { documentId: string; mimeType: string; title: string; heightClass: string; initialPage?: number }) {
  const contentUrl = documentContentUrl(documentId);
  return mimeType === "application/pdf"
    ? <PdfViewer contentUrl={contentUrl} title={title} heightClass={heightClass} initialPage={initialPage} />
    : <ImagePreview contentUrl={contentUrl} title={title} heightClass={heightClass} />;
}

function PdfViewer({ contentUrl, title, heightClass, initialPage }: { contentUrl: string; title: string; heightClass: string; initialPage: number }) {
  const shell = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(Math.max(1, initialPage));
  const [pageCount, setPageCount] = useState(0);
  const [fit, setFit] = useState<FitMode>("width");
  const [zoom, setZoom] = useState(100);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [state, setState] = useState<PdfState>("loading");
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(node);
    return () => observer.disconnect();
  }, [pdf]);

  useEffect(() => {
    let disposed = false;
    let loaded: PDFDocumentProxy | null = null;
    const controller = new AbortController();
    fetch(contentUrl, { credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Preview returned ${response.status}`);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        return pdfjs.getDocument({ data: await response.arrayBuffer() }).promise;
      })
      .then((document) => {
        loaded = document;
        if (disposed) return document.destroy();
        const nextPage = Math.min(Math.max(1, initialPage), document.numPages);
        setPdf(document); setPageCount(document.numPages); setPage(nextPage); setState("rendering");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (!disposed) setState((error as { name?: string }).name === "PasswordException" ? "unsupported" : "error");
      });
    return () => { disposed = true; controller.abort(); void loaded?.destroy(); };
  }, [attempt, contentUrl, initialPage]);

  useEffect(() => {
    if (!pdf || !canvas.current || !size.width || !size.height) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;
    void pdf.getPage(page).then((pdfPage) => {
      if (cancelled || !canvas.current) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const availableWidth = Math.max(240, size.width - 40);
      const availableHeight = Math.max(240, size.height - 40);
      const scale = fit === "width" ? availableWidth / base.width : fit === "page" ? Math.min(availableWidth / base.width, availableHeight / base.height) : zoom / 100;
      const display = pdfPage.getViewport({ scale });
      const quality = Math.min(window.devicePixelRatio || 1, 2);
      const rendered = pdfPage.getViewport({ scale: scale * quality });
      const target = canvas.current;
      target.width = Math.floor(rendered.width); target.height = Math.floor(rendered.height);
      target.style.width = `${Math.floor(display.width)}px`; target.style.height = `${Math.floor(display.height)}px`;
      const context = target.getContext("2d", { alpha: false });
      if (!context) { setState("error"); return; }
      const task = pdfPage.render({ canvas: target, canvasContext: context, viewport: rendered });
      renderTask = task;
      void task.promise.then(() => { if (!cancelled) setState("rendered"); }).catch((error: unknown) => { if ((error as { name?: string }).name !== "RenderingCancelledException") setState("error"); });
    }).catch(() => { if (!cancelled) setState("error"); });
    return () => { cancelled = true; renderTask?.cancel(); };
  }, [fit, page, pdf, size, zoom]);

  const changePage = useCallback((next: number) => {
    const value = Math.min(Math.max(1, next), pageCount);
    setState("rendering");
    setPage(value);
    viewport.current?.scrollTo({ top: 0, behavior: "smooth" });
    const url = new URL(window.location.href);
    if (value === 1) url.searchParams.delete("page"); else url.searchParams.set("page", String(value));
    window.history.replaceState(window.history.state, "", url);
  }, [pageCount]);

  function changeFit(value: FitMode) { setState("rendering"); setFit(value); }
  function adjustZoom(delta: number) { setState("rendering"); setFit("custom"); setZoom((current) => Math.min(200, Math.max(50, current + delta))); }
  if (state === "loading") return <PreviewMessage className={heightClass} title="Preparing document" description="Loading the protected PDF…" />;
  if (state === "error" || state === "unsupported") return <PdfFailure className={heightClass} contentUrl={contentUrl} unsupported={state === "unsupported"} fallback={fallback} openFallback={() => setFallback(true)} retry={() => { setFallback(false); setState("loading"); setPdf(null); setAttempt((value) => value + 1); }} />;

  return <div ref={shell} className={`flex min-w-0 flex-col bg-stone-200/70 ${heightClass}`}>
    <div className="flex min-h-12 flex-wrap items-center gap-1.5 border-b border-stone-200 bg-white px-2 py-1.5 sm:px-3" role="toolbar" aria-label="Document viewer controls">
      <ToolButton label="Previous page" onClick={() => changePage(page - 1)} disabled={page <= 1}><ChevronLeft className="size-4" /></ToolButton>
      <label className="flex items-center gap-1 text-xs text-stone-500"><span className="sr-only">Current page</span><input value={page} min={1} max={pageCount} type="number" onChange={(event) => changePage(Number(event.target.value))} className="h-8 w-11 rounded-md border border-stone-200 bg-stone-50 px-1 text-center text-xs font-medium text-stone-800 outline-none" /><span>/ {pageCount}</span></label>
      <ToolButton label="Next page" onClick={() => changePage(page + 1)} disabled={page >= pageCount}><ChevronRight className="size-4" /></ToolButton>
      <span className="mx-1 hidden h-5 w-px bg-stone-200 sm:block" />
      <ToolButton label="Zoom out" onClick={() => adjustZoom(-10)}><Minus className="size-4" /></ToolButton>
      <span className="min-w-10 text-center text-[11px] tabular-nums text-stone-500">{fit === "custom" ? `${zoom}%` : fit === "width" ? "Width" : "Page"}</span>
      <ToolButton label="Zoom in" onClick={() => adjustZoom(10)}><Plus className="size-4" /></ToolButton>
      <button type="button" onClick={() => changeFit("width")} className={`hidden h-8 rounded-md px-2 text-[11px] font-medium sm:inline-flex sm:items-center ${fit === "width" ? "bg-emerald-50 text-emerald-800" : "text-stone-500 hover:bg-stone-100"}`}>Fit width</button>
      <button type="button" onClick={() => changeFit("page")} className={`hidden h-8 rounded-md px-2 text-[11px] font-medium sm:inline-flex sm:items-center ${fit === "page" ? "bg-emerald-50 text-emerald-800" : "text-stone-500 hover:bg-stone-100"}`}>Fit page</button>
      <div className="ml-auto flex items-center gap-1"><a href={contentUrl} download className="grid size-8 place-items-center rounded-md text-stone-500 hover:bg-stone-100 hover:text-stone-800" aria-label="Download original"><Download className="size-4" /></a><ToolButton label="Full screen" onClick={() => void shell.current?.requestFullscreen()}><Maximize2 className="size-4" /></ToolButton></div>
    </div>
    <div ref={viewport} className="relative min-h-0 flex-1 overflow-auto p-5" tabIndex={0} aria-busy={state === "rendering"} aria-label={`${title}, page ${page} of ${pageCount}`}><canvas ref={canvas} className="mx-auto block bg-white shadow-xl shadow-stone-950/15" />{state === "rendering" ? <div className="absolute inset-0 grid place-items-center bg-stone-100/80" role="status"><p className="rounded-lg bg-white px-3 py-2 text-xs font-medium text-stone-600 shadow-sm">Rendering page {page}…</p></div> : null}</div>
  </div>;
}

function ImagePreview({ contentUrl, title, heightClass }: { contentUrl: string; title: string; heightClass: string }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    const controller = new AbortController();
    fetch(contentUrl, { credentials: "include", headers: { Range: "bytes=0-0" }, signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); void response.body?.cancel(); setState("ready"); })
      .catch((error: unknown) => { if (!(error instanceof DOMException && error.name === "AbortError")) setState("error"); });
    return () => controller.abort();
  }, [attempt, contentUrl]);
  if (state === "loading") return <PreviewMessage className={heightClass} title="Preparing document" description="Loading the protected image…" />;
  if (state === "error") return <PreviewError className={heightClass} retry={() => { setState("loading"); setAttempt((value) => value + 1); }} />;
  return <div className={`relative grid place-items-center overflow-auto bg-stone-200/70 p-5 ${heightClass}`}><a href={contentUrl} download className="absolute right-3 top-3 grid size-9 place-items-center rounded-lg bg-white text-stone-600 shadow-sm" aria-label="Download original"><Download className="size-4" /></a><img key={attempt} src={contentUrl} alt={`Preview of ${title}`} onError={() => setState("error")} className="max-h-[66vh] max-w-full rounded-sm shadow-xl shadow-stone-950/15" /></div>;
}

function ToolButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) { return <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick} className="grid size-8 place-items-center rounded-md text-stone-500 hover:bg-stone-100 hover:text-stone-800 disabled:pointer-events-none disabled:opacity-30">{children}</button>; }
function PreviewMessage({ className, title, description }: { className: string; title: string; description: string }) { return <div className={`grid place-items-center bg-stone-100 ${className}`}><div className="text-center"><Expand className="mx-auto size-5 animate-pulse text-stone-400" /><p className="mt-3 text-sm font-medium text-stone-700">{title}</p><p className="mt-1 text-xs text-stone-400">{description}</p></div></div>; }
function PreviewError({ className, retry }: { className: string; retry: () => void }) { return <div className={`grid place-items-center bg-stone-100 p-6 text-center ${className}`}><div><FileWarning className="mx-auto size-8 text-amber-500" /><p className="mt-3 text-sm font-medium text-stone-800">Preview could not be loaded.</p><p className="mt-1 text-xs text-stone-500">The original document remains protected and unchanged.</p><button type="button" onClick={retry} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 hover:bg-stone-50"><RotateCcw className="size-4" />Retry</button></div></div>; }

function PdfFailure({ className, contentUrl, unsupported, fallback, openFallback, retry }: { className: string; contentUrl: string; unsupported: boolean; fallback: boolean; openFallback: () => void; retry: () => void }) {
  if (fallback) return <div className={`flex flex-col bg-stone-100 ${className}`}><div className="flex items-center justify-between gap-3 border-b border-stone-200 bg-amber-50 px-4 py-2 text-xs text-amber-900"><span>Fallback preview · enhanced controls are unavailable</span><a href={contentUrl} download className="inline-flex items-center gap-1.5 font-medium"><Download className="size-3.5" />Download original</a></div><iframe src={contentUrl} title="Authenticated fallback PDF preview" className="min-h-0 flex-1 border-0" /></div>;
  return <div className={`grid place-items-center bg-stone-100 p-6 text-center ${className}`}><div className="max-w-md"><FileWarning className="mx-auto size-8 text-amber-500" /><p className="mt-3 text-sm font-medium text-stone-800">{unsupported ? "This PDF needs the fallback preview." : "Preview could not be rendered in the enhanced viewer."}</p><p className="mt-1 text-xs leading-5 text-stone-500">{unsupported ? "The document may be encrypted or use an unsupported PDF feature." : "The original document remains protected and unchanged."}</p><div className="mt-5 flex flex-wrap justify-center gap-2"><button type="button" onClick={openFallback} className="inline-flex h-9 items-center rounded-lg bg-stone-900 px-3 text-sm font-medium text-white">Open fallback preview</button><a href={contentUrl} download className="inline-flex h-9 items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 text-sm text-stone-700"><Download className="size-4" />Download original</a><button type="button" onClick={retry} className="inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm text-stone-600 hover:bg-white"><RotateCcw className="size-4" />Retry</button></div></div></div>;
}
