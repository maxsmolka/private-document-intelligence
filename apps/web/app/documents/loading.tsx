export default function DocumentsLoading() {
  return <div className="mx-auto max-w-6xl animate-pulse px-5 py-10 md:px-8"><div className="h-8 w-40 rounded bg-stone-200" /><div className="mt-8 h-10 rounded-lg bg-stone-100" /><div className="mt-4 divide-y divide-stone-100">{[1,2,3,4,5].map((item) => <div key={item} className="flex items-center gap-4 py-4"><div className="size-10 rounded-xl bg-stone-200" /><div className="flex-1"><div className="h-4 w-48 rounded bg-stone-200" /><div className="mt-2 h-3 w-32 rounded bg-stone-100" /></div></div>)}</div></div>;
}

