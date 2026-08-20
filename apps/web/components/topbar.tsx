"use client";

import { LogOut, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

export function Topbar() {
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
    await fetch(`${process.env.NEXT_PUBLIC_PDI_API_URL ?? "http://localhost:8000"}/api/v1/auth/logout`, {
      method: "POST", credentials: "include", headers: csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {},
    });
    router.replace("/login");
    router.refresh();
  }
  return (
    <header className="flex h-16 items-center border-b border-stone-200/70 bg-[#fbfaf7]/90 px-5 backdrop-blur md:px-8">
      <div className="mx-auto flex w-full max-w-6xl items-center">
        <form onSubmit={submit} className="relative w-full max-w-md">
          <label>
            <span className="sr-only">Search documents</span>
            <Search className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-stone-400" />
            <input
              ref={input}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={200}
              placeholder="Search your documents"
              className="h-9 w-full rounded-lg bg-transparent pl-8 pr-14 text-sm text-stone-700 outline-none placeholder:text-stone-400 focus:bg-white focus:ring-2 focus:ring-stone-100"
            />
          </label>
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-stone-200 bg-white px-1.5 py-0.5 font-sans text-[10px] text-stone-400 sm:inline">
            ⌘ K
          </kbd>
        </form>
        <button onClick={logout} className="ml-auto rounded-lg p-2 text-stone-400 hover:bg-stone-100 hover:text-stone-700" aria-label="Sign out"><LogOut className="size-4" /></button>
      </div>
    </header>
  );
}
