import { queryOptions } from "@tanstack/react-query"

import { DocumentsService, HealthService, WorkersService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

export function healthQuery() {
  return queryOptions({
    queryKey: queryKeys.health,
    queryFn: async () => (await HealthService.readHealth()).data,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    staleTime: 20_000,
    retry: false,
  })
}

export function embeddingSummaryQuery() {
  return queryOptions({
    queryKey: queryKeys.embeddingSummary,
    queryFn: async () => (await DocumentsService.readEmbeddingSummary()).data,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  })
}

export function workersQuery() {
  return queryOptions({
    queryKey: queryKeys.workers,
    queryFn: async () => (await WorkersService.readWorkers()).data,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })
}
