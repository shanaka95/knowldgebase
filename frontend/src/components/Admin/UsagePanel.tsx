import { useQuery } from "@tanstack/react-query"
import { Activity } from "lucide-react"
import { useState } from "react"

import type { AdminUsagePoint, UsageFeature } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import {
  DEFAULT_RANGE_DAYS,
  lastDays,
  RangePicker,
} from "@/components/Usage/RangePicker"
import {
  type ChartRow,
  chartConfig,
  UsageChart,
} from "@/components/Usage/UsageChart"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { compactNumber, costFromNanos, fullNumber } from "@/lib/format"
import {
  type Range,
  usageBreakdownQuery,
  usageModelsQuery,
  usageSummaryQuery,
} from "@/queries/usage"

/**
 * Everyone's usage, and what it cost.
 *
 * Superuser-only, and the only place cost appears anywhere in the product. The
 * summary answers "how much, over what, day by day"; the breakdown answers "by
 * whom", for whichever dimension is selected.
 */

const BREAKDOWNS = [
  { value: "user", label: "By account" },
  { value: "group", label: "By group" },
  { value: "model", label: "By model" },
  { value: "feature", label: "By activity" },
] as const

type Breakdown = (typeof BREAKDOWNS)[number]["value"]

const ALL = "__all__"

export function UsagePanel() {
  const [range, setRange] = useState<Range>(() => lastDays(DEFAULT_RANGE_DAYS))
  const [by, setBy] = useState<Breakdown>("user")
  const [model, setModel] = useState<string | undefined>()
  const [feature, setFeature] = useState<UsageFeature | undefined>()

  const filters = { ...range, model, feature }
  const summary = useQuery(usageSummaryQuery(filters))
  const breakdown = useQuery(usageBreakdownQuery(filters, by))
  const models = useQuery(usageModelsQuery(range))

  return (
    <div className="flex flex-col gap-6" data-testid="admin-usage">
      <div className="flex flex-col gap-2">
        <p className="text-muted-foreground text-sm">
          What every account has asked of the models, and what the provider
          charged for it. Days run midnight to midnight UTC.
        </p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <RangePicker value={range} onChange={setRange} />
          <div className="flex items-center gap-2">
            <Select
              value={feature ?? ALL}
              onValueChange={(v) =>
                setFeature(v === ALL ? undefined : (v as UsageFeature))
              }
            >
              <SelectTrigger
                className="h-8 w-40"
                aria-label="Activity"
                data-testid="usage-feature-filter"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All activity</SelectItem>
                {FEATURES.map((f) => (
                  <SelectItem key={f.value} value={f.value}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={model ?? ALL}
              onValueChange={(v) => setModel(v === ALL ? undefined : v)}
            >
              <SelectTrigger
                className="h-8 w-56"
                aria-label="Model"
                data-testid="usage-model-filter"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All models</SelectItem>
                {(models.data ?? []).map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {summary.isPending ? (
        <div className="flex flex-col gap-4" aria-busy>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : summary.error ? (
        <EmptyState
          icon={Activity}
          title="Usage could not be loaded"
          description={summary.error.message || "Try a different date range."}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat
              label="Spend"
              value={costFromNanos(summary.data.totals.cost_nanos)}
              testId="usage-total-cost"
            />
            <Stat
              label="Model calls"
              value={compactNumber(summary.data.totals.requests)}
              title={fullNumber(summary.data.totals.requests)}
            />
            <Stat
              label="Input tokens"
              value={compactNumber(summary.data.totals.input_tokens)}
              title={fullNumber(summary.data.totals.input_tokens)}
            />
            <Stat
              label="Output tokens"
              value={compactNumber(summary.data.totals.output_tokens)}
              title={fullNumber(summary.data.totals.output_tokens)}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Spend, day by day</CardTitle>
            </CardHeader>
            <CardContent>
              <UsageChart
                rows={summary.data.by_day.map(
                  (p): ChartRow => ({
                    day: p.key,
                    cost: p.totals.cost_nanos / 1_000_000_000,
                  }),
                )}
                config={chartConfig([{ key: "cost", label: "Spend" }])}
                formatValue={(v) => costFromNanos(v * 1_000_000_000)}
              />
            </CardContent>
          </Card>
        </>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-base">Where it went</CardTitle>
          <Tabs value={by} onValueChange={(v) => setBy(v as Breakdown)}>
            <TabsList>
              {BREAKDOWNS.map((b) => (
                <TabsTrigger
                  key={b.value}
                  value={b.value}
                  data-testid={`usage-by-${b.value}`}
                >
                  {b.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </CardHeader>
        <CardContent>
          {breakdown.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : breakdown.error ? (
            <p className="text-muted-foreground text-sm">
              {breakdown.error.message}
            </p>
          ) : breakdown.data.data.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing recorded in this range.
            </p>
          ) : (
            <BreakdownTable
              rows={breakdown.data.data}
              showGroup={by === "user"}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}

const FEATURES: { value: UsageFeature; label: string }[] = [
  { value: "ask", label: "Questions" },
  { value: "search", label: "Searches" },
  { value: "import", label: "Imports" },
  { value: "indexing", label: "Indexing" },
  { value: "translation", label: "Translations" },
  { value: "suggestions", label: "Example searches" },
  { value: "agent", label: "Agents" },
]

function Stat({
  label,
  value,
  title,
  testId,
}: {
  label: string
  value: string
  title?: string
  testId?: string
}) {
  return (
    <Card data-testid={testId}>
      <CardContent className="pt-6">
        <p className="font-semibold text-2xl tabular-nums" title={title}>
          {value}
        </p>
        <p className="mt-1 text-muted-foreground text-sm">{label}</p>
      </CardContent>
    </Card>
  )
}

function BreakdownTable({
  rows,
  showGroup,
}: {
  rows: AdminUsagePoint[]
  showGroup: boolean
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="usage-breakdown">
        <thead className="text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 pr-4 text-left font-medium">Name</th>
            {showGroup && (
              <th className="py-1.5 pr-4 text-left font-medium">Group</th>
            )}
            <th className="py-1.5 pr-4 text-right font-medium">Calls</th>
            <th className="py-1.5 pr-4 text-right font-medium">In</th>
            <th className="py-1.5 pr-4 text-right font-medium">Out</th>
            <th className="py-1.5 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.key}
              className="border-b last:border-0"
              data-testid="usage-row"
            >
              <td className="py-1.5 pr-4">
                <span className="break-all">{row.label ?? row.key}</span>
              </td>
              {showGroup && (
                <td className="py-1.5 pr-4">
                  {row.group ? (
                    <Badge variant="secondary" className="font-normal">
                      {row.group.name}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </td>
              )}
              <Cell value={row.totals.requests} />
              <Cell value={row.totals.input_tokens} />
              <Cell value={row.totals.output_tokens} />
              <td
                className="py-1.5 text-right font-mono tabular-nums"
                data-testid="usage-cost"
              >
                {costFromNanos(row.totals.cost_nanos)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Cell({ value }: { value: number }) {
  return (
    <td
      className="py-1.5 pr-4 text-right font-mono text-muted-foreground tabular-nums"
      title={fullNumber(value)}
    >
      {value > 0 ? compactNumber(value) : "-"}
    </td>
  )
}
