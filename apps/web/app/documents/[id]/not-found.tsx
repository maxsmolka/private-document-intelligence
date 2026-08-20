import Link from "next/link";
export default function NotFound() { return <div className="mx-auto max-w-lg px-6 py-28 text-center"><p className="text-sm text-stone-400">404</p><h1 className="mt-3 text-2xl font-semibold text-stone-900">Document not found</h1><p className="mt-2 text-sm text-stone-500">It may have been removed or the link is incorrect.</p><Link href="/documents" className="mt-6 inline-flex rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white">Back to documents</Link></div>; }

