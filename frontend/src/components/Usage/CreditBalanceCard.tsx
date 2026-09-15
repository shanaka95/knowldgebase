import { useQuery } from "@tanstack/react-query"

import { UsageService } from "@/client"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { shortDate } from "@/lib/format"
import { queryKeys } from "@/lib/queryKeys"
import { cn } from "@/lib/utils"

/**
 * What this account has left to spend this month.
 *
 * The headline is what remains rather than what was used: somebody opening
 * this wants to know whether they can carry on, and a bar filling up answers a
 * different question from one draining. The renewal date is beside it because
 * "you have 12 left" is only actionable with "until the 1st".
 *
 * No money anywhere — a credit is what you may spend, not what it cost us.
 */

export function creditBalanceQuery() {
  return {
    queryKey: queryKeys.usage.credits(),
    queryFn: async () => (await UsageService.readMyCredits()).data,
    staleTime: 30_000,
  }
}

const DECIMALS = { maximumFractionDigits: 1 }

function credits(value: number): string {
  return new Intl.NumberFormat(undefined, DECIMALS).format(value)
}

export function CreditBalanceCard({ className }: { className?: string }) {
  const { data, isPending, error } = useQuery(creditBalanceQuery())

  if (isPending) return <Skeleton className={cn("h-28 w-full", className)} />
  if (error || !data) return null

  const total = data.allowance + data.granted
  // Filled by what is *left*, not what was spent. The track is a pale version
  // of the same colour, so an empty bar reads as a full one at this height -
  // and a balance is a fuel gauge, not a progress bar.
  const leftPercent =
    total > 0 ? Math.max(0, Math.min(100, (data.remaining / total) * 100)) : 0
  const spent = [
    { label: "Questions", value: data.used_on_answers },
    { label: "Searches", value: data.used_on_search },
    { label: "Indexing", value: data.used_on_indexing },
    { label: "Other", value: data.used_on_other },
  ].filter((part) => part.value > 0)

  const low = data.remaining <= total * 0.1
  const out = data.remaining <= 0

  return (
    <Card className={className} data-testid="credit-balance">
      <CardContent className="flex flex-col gap-3 pt-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="flex items-baseline gap-2">
            <span
              className={cn(
                "font-semibold text-3xl tabular-nums",
                out && "text-destructive",
              )}
              data-testid="credits-remaining"
            >
              {credits(data.remaining)}
            </span>
            <span className="text-muted-foreground text-sm">
              of {credits(total)} credits left
            </span>
          </span>
          <span className="text-muted-foreground text-sm">
            Renews {shortDate(data.renews_at)}
          </span>
        </div>

        <Progress
          value={leftPercent}
          className={cn(
            "h-2",
            out && "[&>*]:bg-destructive",
            low && "[&>*]:bg-warning",
          )}
          aria-label="Credits left this month"
        />

        {out ? (
          <p className="text-destructive text-sm">
            You have used everything for this month. An administrator can raise
            your limit or add credits.
          </p>
        ) : low ? (
          <p className="text-sm text-warning-foreground">
            Running low. An administrator can raise your limit or add credits.
          </p>
        ) : null}

        {spent.length > 0 && (
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground text-xs">
            {spent.map((part) => (
              <div key={part.label} className="flex items-baseline gap-1.5">
                <dt>{part.label}</dt>
                <dd className="font-mono text-foreground tabular-nums">
                  {credits(part.value)}
                </dd>
              </div>
            ))}
            {data.granted > 0 && (
              <div className="flex items-baseline gap-1.5">
                <dt>Includes granted</dt>
                <dd className="font-mono text-foreground tabular-nums">
                  {credits(data.granted)}
                </dd>
              </div>
            )}
          </dl>
        )}

        <p className="text-muted-foreground text-xs">
          One credit is a thousand tokens, ten embeddings, or ten rerank calls.
        </p>
      </CardContent>
    </Card>
  )
}
