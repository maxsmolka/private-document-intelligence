import type { Metadata } from "next";
import { DocumentExplorer } from "@/components/document-explorer";
import { UploadDialog } from "@/components/upload-dialog";
import { getDocuments } from "@/lib/api/server";

export const metadata: Metadata = { title: "Documents" };

export default async function DocumentsPage({ searchParams }: { searchParams: Promise<{ status?: string; life_area?: string }> }) {
  const filters = await searchParams;
  let data;
  try { data = await getDocuments({ status: filters.status, lifeArea: filters.life_area }); }
  catch { data = { items: [], total: 0, limit: 50, offset: 0 }; }
  return (
    <div className="mx-auto max-w-6xl px-5 py-8 md:px-8 md:py-10">
      <div className="flex items-center justify-between"><div><h1 className="text-2xl font-semibold tracking-[-0.025em] text-stone-950">Documents</h1><p className="mt-1 text-sm text-stone-500">{data.total} {data.total === 1 ? "document" : "documents"} in your private archive</p></div><UploadDialog /></div>
      <DocumentExplorer documents={data.items} />
    </div>
  );
}
