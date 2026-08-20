import { Search } from "lucide-react";

export function Topbar() {
  return (
    <header className="flex h-16 items-center border-b border-stone-200/70 bg-[#fbfaf7]/90 px-5 backdrop-blur md:px-8">
      <div className="mx-auto flex w-full max-w-6xl items-center">
        <div className="flex items-center gap-2 text-sm text-stone-400">
          <Search className="size-4" />
          <span>Search your documents</span>
          <kbd className="ml-2 hidden rounded border border-stone-200 bg-white px-1.5 py-0.5 font-sans text-[11px] text-stone-400 sm:inline">⌘ K</kbd>
        </div>
        <div className="ml-auto size-8 rounded-full bg-gradient-to-br from-amber-100 to-stone-200 ring-1 ring-stone-200" aria-label="Local PDI profile" />
      </div>
    </header>
  );
}

