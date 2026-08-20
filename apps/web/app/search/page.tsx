import type { Metadata } from "next";
import { SearchWorkspace } from "@/components/search-workspace";
import { getSearch, type SearchResponse } from "@/lib/api/documents";

export const metadata: Metadata = { title: "Search" };

interface SearchParameters {
  q?: string;
  offset?: string;
  status?: string;
  life_area?: string;
  document_type?: string;
  date_from?: string;
  date_to?: string;
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParameters> }) {
  const filters = await searchParams;
  const offset = Math.max(0, Number.parseInt(filters.offset ?? "0", 10) || 0);
  let data: SearchResponse;
  let unavailable = false;
  try {
    data = await getSearch({
      q: filters.q,
      offset,
      status: filters.status,
      lifeArea: filters.life_area,
      documentType: filters.document_type,
      dateFrom: filters.date_from,
      dateTo: filters.date_to,
    });
  } catch {
    unavailable = true;
    data = { schema_version: "1", query: filters.q ?? "", total: 0, limit: 25, offset, results: [] };
  }
  return <SearchWorkspace data={data} filters={filters} unavailable={unavailable} />;
}
