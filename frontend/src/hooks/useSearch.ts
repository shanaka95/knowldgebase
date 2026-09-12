import { useQuery } from "@tanstack/react-query"

import {
  type RetrieveParams,
  retrieveQuery,
  searchQuery,
} from "@/queries/search"
import { useDebouncedValue } from "./useDebouncedValue"

/** Fast Postgres full-text search — used by the command palette. */
export function useSearch(q: string, namespaceId?: string | null) {
  const debounced = useDebouncedValue(q, 250)
  const query = useQuery(searchQuery(debounced, namespaceId))
  return { ...query, debouncedQuery: debounced.trim() }
}

/** Hybrid search (BM25 + vectors, RRF-fused) — used by the search page. */
export function useHybridSearch(params: RetrieveParams) {
  const debounced = useDebouncedValue(params.q, 250)
  const query = useQuery(retrieveQuery({ ...params, q: debounced }))
  return { ...query, debouncedQuery: debounced.trim() }
}
