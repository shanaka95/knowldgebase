import { queryOptions } from "@tanstack/react-query"

import {
  type AdminUsageBreakdown,
  AdminUsageService,
  type AdminUsageSummary,
  type MyUsage,
  type UsageFeature,
  UsageService,
} from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** The range every usage query is asked for. Both ends inclusive, both UTC. */
export type Range = { from: string; to: string }

/** Filters the admin views share, so drilling in changes one parameter. */
export type UsageFilters = Range & {
  userId?: string
  groupId?: string
  feature?: UsageFeature
  model?: string
}

/** One account's own usage. Cost is not in this reply and cannot be. */
export function myUsageQuery(range: Range) {
  return queryOptions({
    queryKey: queryKeys.usage.mine(range),
    queryFn: async (): Promise<MyUsage> =>
      (
        await UsageService.readMyUsage({
          query: { from: range.from, to: range.to },
        })
      ).data,
  })
}

function adminQuery(filters: UsageFilters) {
  return {
    from: filters.from,
    to: filters.to,
    user_id: filters.userId,
    group_id: filters.groupId,
    feature: filters.feature,
    model: filters.model,
  } as const
}

/** Totals for the range, split by feature and by day — with cost. */
export function usageSummaryQuery(filters: UsageFilters) {
  return queryOptions({
    queryKey: queryKeys.admin.usage({ ...filters, kind: "summary" }),
    queryFn: async (): Promise<AdminUsageSummary> =>
      (await AdminUsageService.readUsageSummary({ query: adminQuery(filters) }))
        .data,
  })
}

/** Who or what the spend went on, largest first. */
export function usageBreakdownQuery(
  filters: UsageFilters,
  by: "user" | "model" | "group" | "feature",
) {
  return queryOptions({
    queryKey: queryKeys.admin.usage({ ...filters, by }),
    queryFn: async (): Promise<AdminUsageBreakdown> =>
      (
        await AdminUsageService.readUsageBreakdown({
          query: { ...adminQuery(filters), by },
        })
      ).data,
  })
}

/**
 * Models that have actually answered something in the range.
 *
 * Read from the data rather than from configuration, so the filter offers a
 * model retired last month that appears in last month's rows, and not one that
 * is configured but has never been used.
 */
export function usageModelsQuery(range: Range) {
  return queryOptions({
    queryKey: queryKeys.admin.usageModels(range),
    queryFn: async (): Promise<string[]> =>
      (
        await AdminUsageService.readModelsSeen({
          query: { from: range.from, to: range.to },
        })
      ).data,
    staleTime: 5 * 60_000,
  })
}
