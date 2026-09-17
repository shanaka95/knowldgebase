import { useQuery } from "@tanstack/react-query"
import { Activity } from "lucide-react"
import type { UsagePoint, UsageTotals } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import {
  type ChartRow,
  chartConfig,
  UsageChart,
} from "@/components/Usage/UsageChart"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { compactNumber, fullNumber } from "@/lib/format"
import { myUsageQuery, type Range } from "@/queries/usage"

/**
 * What one person did, and what it took.
 *
 * Activity leads and tokens follow: "142 questions" is a figure somebody can
 * act on, and a token count is context for it. There is no cost here, and the
 * reply this reads has no field to put one in.
 */

// The features worth a card of their own, and what to call them. Anything else
// the backend records still appears in the chart and the table below.
const HEADLINE = [
  { key: "ask", label: "Questions asked" },
  { key: "search", label: "Searches run" },
  { key: "import", label: "Pages imported" },
  { key: "translation", label: "Translations" },
] as const

export function MyUsagePanel({ range }: { range: Range }) {
  const { data, isPending, error } = useQuery(myUsageQuery(range))

  if (isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }

  if (error) {
    return (
      <EmptyState
        icon={Activity}
        title="Usage could not be loaded"
        description={error.message || "Try a different date range."}
      />
    )
  }

  const byFeature = new Map(data.by_feature.map((p) => [p.key, p]))
  const anything = data.totals.requests > 0

  return (
    <div className="flex flex-col gap-6" data-testid="my-usage">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {HEADLINE.map(({ key, label }) => (
          <ActivityCard
            key={key}
            label={label}
            value={byFeature.get(key)?.totals.requests ?? 0}
            testId={`usage-count-${key}`}
          />
        ))}
      </div>

      {anything ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Day by day</CardTitle>
            </CardHeader>
            <CardContent>
              <DailyChart points={data.by_day} />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  What you used it for
                </CardTitle>
              </CardHeader>
              <CardContent>
                <PointTable points={data.by_feature} first="Activity" />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Models that answered
                </CardTitle>
              </CardHeader>
              <CardContent>
                <PointTable points={data.by_model} first="Model" showKind />
              </CardContent>
            </Card>
          </div>

          <TokenDetail totals={data.totals} />
        </>
      ) : (
        <EmptyState
          icon={Activity}
          title="Nothing in this range"
          description="Ask a question or run a search and it will show up here."
        />
      )}

      <p className="text-xs text-muted-foreground">
        Days run midnight to midnight UTC.
      </p>
    </div>
  )
}

function ActivityCard({
  label,
  value,
  testId,
}: {
  label: string
  value: number
  testId: string
}) {
  return (
    <Card data-testid={testId}>
      <CardContent className="pt-6">
        <p
          className="font-semibold text-3xl tabular-nums"
          title={fullNumber(value)}
        >
          {compactNumber(value)}
        </p>
        <p className="mt-1 text-muted-foreground text-sm">{label}</p>
      </CardContent>
    </Card>
  )
}

function DailyChart({ points }: { points: UsagePoint[] }) {
  const rows: ChartRow[] = points.map((p) => ({
    day: p.key,
    requests: p.totals.requests,
  }))
  return (
    <UsageChart
      rows={rows}
      config={chartConfig([{ key: "requests", label: "Activity" }])}
    />
  )
}

function PointTable({
  points,
  first,
  showKind = false,
}: {
  points: UsagePoint[]
  first: string
  showKind?: boolean
}) {
  if (points.length === 0) {
    return <p className="text-muted-foreground text-sm">Nothing yet.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-muted-foreground">
          <tr className="border-b">
            <th className="py-1.5 pr-4 text-left font-medium">{first}</th>
            <th className="py-1.5 pr-4 text-right font-medium">Uses</th>
            <th className="py-1.5 text-right font-medium">Tokens</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => {
            const tokens = p.totals.input_tokens + p.totals.output_tokens
            return (
              <tr key={p.key} className="border-b last:border-0">
                <td className="py-1.5 pr-4">
                  <span className="break-all">{p.label ?? p.key}</span>
                  {showKind && p.label && (
                    <span className="ml-1.5 text-muted-foreground text-xs">
                      {p.key !== p.label ? p.label : null}
                    </span>
                  )}
                </td>
                <td
                  className="py-1.5 pr-4 text-right font-mono tabular-nums"
                  title={fullNumber(p.totals.requests)}
                >
                  {compactNumber(p.totals.requests)}
                </td>
                <td
                  className="py-1.5 text-right font-mono text-muted-foreground tabular-nums"
                  title={fullNumber(tokens)}
                >
                  {tokens > 0 ? compactNumber(tokens) : "-"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function TokenDetail({ totals }: { totals: UsageTotals }) {
  const items = [
    { label: "Input tokens", value: totals.input_tokens },
    { label: "Output tokens", value: totals.output_tokens },
    { label: "Reused from cache", value: totals.cached_tokens },
    { label: "Reranker calls", value: totals.search_units },
    { label: "Seconds dictated", value: totals.audio_seconds },
  ]
  return (
    <div className="rounded-lg border bg-muted/20 px-4 py-3">
      <p className="font-medium text-sm">Details</p>
      <dl className="mt-2 flex flex-wrap gap-x-8 gap-y-2 text-sm">
        {items.map((item) => (
          <div key={item.label} className="flex items-baseline gap-2">
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd
              className="font-mono tabular-nums"
              title={fullNumber(item.value)}
            >
              {compactNumber(item.value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
