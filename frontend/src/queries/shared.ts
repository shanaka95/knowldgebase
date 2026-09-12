import { queryOptions } from "@tanstack/react-query"

import { DocumentsService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function sharedWithMeQuery() {
  return queryOptions({
    queryKey: queryKeys.shared,
    queryFn: async () => (await DocumentsService.readSharedWithMe()).data,
  })
}

export function recentDocumentsQuery(limit = 20) {
  return queryOptions({
    queryKey: queryKeys.documents.recent(),
    queryFn: async () =>
      (await DocumentsService.readRecentDocuments({ query: { limit } })).data,
    staleTime: 15_000,
  })
}
