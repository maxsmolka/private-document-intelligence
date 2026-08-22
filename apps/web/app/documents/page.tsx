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
    <div className="page">
      <div className="flex items-center justify-between gap-4"><div><p className="eyebrow">Library</p><h1 className="page-title mt-1">Documents</h1><p className="page-description">{data.total} {data.total === 1 ? "document" : "documents"} in your private archive</p></div><UploadDialog /></div>
      <DocumentExplorer documents={data.items} />
    </div>
  );
}
