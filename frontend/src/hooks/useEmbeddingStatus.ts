import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"

import { deriveEmbeddingState } from "@/lib/embeddingState"
import { queryKeys } from "@/lib/queryKeys"
import {
  documentEmbeddingsQuery,
  IN_PROGRESS_STATUSES,
} from "@/queries/documents"

/**
 * Live embedding status for a document. Polls while a job runs and, when the
 * pipeline reaches a terminal state, refreshes the document, the space tree
 * and the dashboard summary so status dots update everywhere.
 */
export function useEmbeddingStatus(
  documentId: string,
  namespaceId?: string | null,
  options: { enabled?: boolean } = {},
) {
  const queryClient = useQueryClient()
  const query = useQuery({
    ...documentEmbeddingsQuery(documentId),
    enabled: options.enabled ?? true,
  })
  const data = query.data
  const previousStatus = useRef<string | null>(null)

  useEffect(() => {
    const status = data?.embedding_status ?? null
    const prev = previousStatus.current
    previousStatus.current = status
    if (!status || !prev) return
    const wasRunning = IN_PROGRESS_STATUSES.has(prev)
    const isRunning = IN_PROGRESS_STATUSES.has(status)
    if (wasRunning && !isRunning) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.embeddingSummary,
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.documents.recent(),
      })
      if (namespaceId) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.namespaces.tree(namespaceId),
        })
      }
    }
  }, [data?.embedding_status, documentId, namespaceId, queryClient])

  const state = deriveEmbeddingState(data)
  const inProgress = data
    ? IN_PROGRESS_STATUSES.has(data.embedding_status)
    : false

  return {
    ...query,
    state,
    inProgress,
    currentJob: data?.current_job ?? null,
    progress: data?.current_job?.progress ?? null,
  }
}
