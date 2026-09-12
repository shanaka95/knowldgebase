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
            namespace_id: namespaceId ?? undefined,
            rrf_k: rrfK,
            candidates_per_source: candidates,
            limit,
          },
        })
      ).data,
    // The server rejects "no method selected"; asking would only 422.
    enabled: trimmed.length > 0 && (bm25 || vector) && targets.length > 0,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: false,
  })
}
