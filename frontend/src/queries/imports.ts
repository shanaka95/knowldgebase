import { queryOptions } from "@tanstack/react-query"

import { type ImportJobPublic, ImportsService } from "@/client"

/**
 * Keys live here rather than in the shared factory so the imports feature owns
 * its own cache namespace.
 */
export const importKeys = {
  all: ["imports"] as const,
  list: (namespaceId?: string | null) =>
    ["imports", "list", namespaceId ?? null] as const,
  detail: (id: string) => ["imports", id] as const,
}

/** Statuses where the worker is still going to change something. */
export const ACTIVE_IMPORT_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "rendering",
  "parsing",
  "creating",
])

export function isImportActive(job: Pick<ImportJobPublic, "status">): boolean {
  return ACTIVE_IMPORT_STATUSES.has(job.status)
}

/** Polls every 2 s while any job is still running, then stops. */
export function importsQuery(namespaceId?: string | null) {
  return queryOptions({
    queryKey: importKeys.list(namespaceId),
    queryFn: async () =>
      (
        await ImportsService.readImports({
          query: {
            ...(namespaceId ? { namespace_id: namespaceId } : {}),
            limit: 100,
          },
        })
      ).data,
    refetchInterval: (query) =>
      (query.state.data?.data ?? []).some(isImportActive) ? 2_000 : false,
    refetchIntervalInBackground: false,
    staleTime: 1_000,
  })
}

export function importQuery(importId: string) {
  return queryOptions({
    queryKey: importKeys.detail(importId),
    queryFn: async (): Promise<ImportJobPublic> =>
      (await ImportsService.readImport({ path: { import_id: importId } })).data,
    refetchInterval: (query) =>
      query.state.data && isImportActive(query.state.data) ? 2_000 : false,
    refetchIntervalInBackground: false,
  })
}
