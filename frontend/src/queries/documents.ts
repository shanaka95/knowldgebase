import { queryOptions } from "@tanstack/react-query"

import {
  type DocumentEmbeddingsPublic,
  type DocumentPublic,
  DocumentsService,
  type DocumentTypesPublic,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export const IN_PROGRESS_STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "chunking",
  "summarizing",
  "embedding",
])

export function documentQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.detail(documentId),
    queryFn: async (): Promise<DocumentPublic> =>
      (
        await DocumentsService.readDocument({
          path: { document_id: documentId },
        })
      ).data,
  })
}

/** Polls every 2 s while the pipeline is running, stops on a terminal state. */
export function documentEmbeddingsQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.documents.embeddings(documentId),
    queryFn: async (): Promise<DocumentEmbeddingsPublic> =>
      (
        await DocumentsService.readDocumentEmbeddings({
          path: { document_id: documentId },
        })
      ).data,
    refetchInterval: (query) => {
      const status = query.state.data?.embedding_status
      return status && IN_PROGRESS_STATUSES.has(status) ? 2_000 : false
    },
    refetchIntervalInBackground: false,
    staleTime: 1_000,
  })
}

/**
 * The page types this account already uses (with counts), followed by common
 * suggestions. A suggestion list, not a closed set — any short string is valid.
 */
export function documentTypesQuery() {
  return queryOptions({
    queryKey: queryKeys.documents.types(),
    queryFn: async (): Promise<DocumentTypesPublic> =>
      (await DocumentsService.readDocumentTypes()).data,
    staleTime: 60_000,
  })
}
