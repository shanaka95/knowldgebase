import { queryOptions } from "@tanstack/react-query"

import { ApiKeysService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function apiKeysQuery() {
  return queryOptions({
    queryKey: queryKeys.apiKeys,
    queryFn: async () => (await ApiKeysService.readApiKeys()).data,
  })
}
