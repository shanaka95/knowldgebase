import { queryOptions } from "@tanstack/react-query"

import { SearchService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"
import {
  type SearchTarget,
  serializeTargets,
  toEmbeddingKinds,
} from "@/lib/searchPrefs"

export function searchQuery(
  q: string,
  namespaceId?: string | null,
  limit = 20,
) {
  const trimmed = q.trim()
  return queryOptions({
    queryKey: queryKeys.search(trimmed, namespaceId),
    queryFn: async () =>
      (
        await SearchService.searchDocuments({
          query: { q: trimmed, namespace_id: namespaceId ?? undefined, limit },
        })
      ).data,
    enabled: trimmed.length > 0,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  })
}

export interface RetrieveParams {
  q: string
  bm25: boolean
  vector: boolean
  targets: SearchTarget[]
  namespaceId?: string | null
  rrfK?: number
  candidates?: number
  limit?: number
  /** Which corpora to look in. Both by default; the server defaults notes off. */
  pages?: boolean
  notes?: boolean
}

/**
 * Hybrid retrieval: BM25 and/or vector search across page, summary and chunks,
 * fused with Reciprocal Rank Fusion.
 */
export function retrieveQuery({
  q,
  bm25,
  vector,
  targets,
  pages = true,
  notes = true,
  namespaceId,
  rrfK,
  candidates,
  limit = 20,
}: RetrieveParams) {
  const trimmed = q.trim()
  return queryOptions({
    queryKey: [
      "search",
      "retrieve",
      trimmed,
      namespaceId ?? null,
      bm25,
      vector,
      serializeTargets(targets),
      // In the key, not just the request. Without these a result cached for
      // "pages only" would be served for "pages and notes" - the same query
      // string, a different answer.
      pages,
      notes,
      rrfK ?? null,
      candidates ?? null,
      limit,
    ] as const,
    queryFn: async () =>
      (
        await SearchService.retrieveDocuments({
          query: {
            q: trimmed,
            bm25,
            vector,
            targets: toEmbeddingKinds(targets),
            include_pages: pages,
            include_notes: notes,
            namespace_id: namespaceId ?? undefined,
            rrf_k: rrfK,
            candidates_per_source: candidates,
            limit,
          },
        })
      ).data,
    // The server rejects "no method selected"; asking would only 422.
    enabled:
      trimmed.length > 0 &&
      (bm25 || vector) &&
      (pages || notes) &&
      // Targets only constrain the page corpus, so a notes-only search does
      // not need one.
      (!pages || targets.length > 0),
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: false,
  })
}

/**
 * Example searches written from this person's own pages.
 *
 * Private to them, and different ones each time, so an empty search box does
 * not become wallpaper. `staleTime: 0` for that reason - the point is that it
 * changes.
 */
export function searchSuggestionsQuery() {
  return queryOptions({
    queryKey: queryKeys.searchSuggestions(),
    queryFn: async () => (await SearchService.readSearchSuggestions()).data,
    staleTime: 0,
    gcTime: 0,
  })
}
