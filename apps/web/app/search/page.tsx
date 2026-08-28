import type { Metadata } from "next";
import { SearchWorkspace } from "@/components/search-workspace";
import type { SavedSearch, SearchResponse } from "@/lib/api/documents";
import { getSavedSearches, getSearch } from "@/lib/api/server";

export const metadata: Metadata = { title: "Search" };

interface SearchParameters {
  q?: string;
  offset?: string;
  status?: string;
  life_area?: string;
  document_type?: string;
  date_from?: string;
  date_to?: string;
  organization_id?: string;
  contract_id?: string;
  has_event?: string;
  has_deadline?: string;
  amount_min?: string;
  amount_max?: string;
  source?: string;
  tag?: string;
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<SearchParameters> }) {
  const filters = await searchParams;
  const offset = Math.max(0, Number.parseInt(filters.offset ?? "0", 10) || 0);
  let data: SearchResponse;
  let savedSearches: SavedSearch[] = [];
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
      organizationId: filters.organization_id,
      contractId: filters.contract_id,
      hasEvent: filters.has_event,
      hasDeadline: filters.has_deadline,
      amountMin: filters.amount_min,
      amountMax: filters.amount_max,
      source: filters.source,
      tag: filters.tag,
    });
  } catch {
    unavailable = true;
    data = {
      schema_version: "2", query: filters.q ?? "", total: 0, limit: 25, offset, results: [],
      facets: { document_types: [], organizations: [], years: [], review_states: [], sources: [] },
    };
  }
  try {
    savedSearches = await getSavedSearches();
  } catch {
    savedSearches = [];
  }
  return <SearchWorkspace data={data} filters={filters} unavailable={unavailable} savedSearches={savedSearches} />;
}
