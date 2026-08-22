"use client";

import { LogOut, Menu, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { browserApiUrl } from "@/lib/api/documents";

export function Topbar({ onOpenNavigation }: { onOpenNavigation: () => void }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  useEffect(() => {
    function shortcut(event: globalThis.KeyboardEvent) {
      const target = event.target;
      const editing =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
      if (event.key === "/" && !editing) {
        event.preventDefault();
        input.current?.focus();
      }
      if (event.key === "Escape" && document.activeElement === input.current) {
        setQuery("");
        input.current?.blur();
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  function submit(event: FormEvent) {
    event.preventDefault();
    router.push(query.trim() ? `/search?q=${encodeURIComponent(query.trim())}` : "/search");
  }
  async function logout() {
    const csrf = document.cookie.split("; ").find((value) => value.startsWith("pdi_csrf="))?.split("=")[1];
    await fetch(browserApiUrl("/api/v1/auth/logout"), {
      method: "POST", credentials: "include", headers: csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {},
    });
    router.replace("/login");
    router.refresh();
  }
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center border-b border-stone-200/80 bg-[#f7f7f5]/90 px-4 backdrop-blur-xl sm:px-6 md:px-8">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-2">
        <button type="button" onClick={onOpenNavigation} className="grid size-9 shrink-0 place-items-center rounded-lg text-stone-600 hover:bg-white md:hidden" aria-label="Open navigation"><Menu className="size-5" /></button>
        <form onSubmit={submit} className="relative w-full max-w-md">
          <label>
            <span className="sr-only">Search all document text and metadata</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-400" />
            <input
              ref={input}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={200}
              placeholder="Search PDI"
              className="h-9 w-full rounded-lg border border-transparent bg-transparent pl-9 pr-14 text-sm text-stone-700 outline-none placeholder:text-stone-500 focus:border-stone-200 focus:bg-white focus:ring-2 focus:ring-emerald-900/5"
            />
          </label>
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-stone-200 bg-white px-1.5 py-0.5 font-sans text-[10px] text-stone-400 sm:inline">
            ⌘K
          </kbd>
        </form>
        <button onClick={logout} className="ml-auto rounded-lg p-2 text-stone-400 hover:bg-white hover:text-stone-700" aria-label="Sign out"><LogOut className="size-4" /></button>
      </div>
    </header>
  );
}
