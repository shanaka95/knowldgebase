import { useQuery, useSuspenseQuery } from "@tanstack/react-query"

import { documentQuery } from "@/queries/documents"

export function useDocument(documentId: string) {
  return useSuspenseQuery(documentQuery(documentId))
}

/**
 * Same query, but polling — used in view mode to surface "a newer version
 * exists" without refetching while the user is typing.
 */
export function useDocumentPolling(documentId: string, enabled: boolean) {
  return useQuery({
    ...documentQuery(documentId),
    enabled,
    refetchInterval: enabled ? 30_000 : false,
    refetchIntervalInBackground: false,
  })
}
