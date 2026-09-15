import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { Coins } from "lucide-react"

import { creditBalanceQuery } from "@/components/Usage/CreditBalanceCard"
import { useSidebar } from "@/components/ui/sidebar"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/**
 * How much is left, where it can be seen without going to look for it.
 *
 * Running out mid-question is the worst way to find out there was a limit, so
 * the number lives in the shell rather than only on the usage page. It is
 * quiet until it matters: grey most of the time, amber under a tenth, red at
 * zero.
 *
 * Collapsed to the icon rail it becomes the coin alone with the figure in its
 * tooltip — the rail is 48px wide and a number would not fit honestly.
 */

function compact(value: number): string {
  return new Intl.NumberFormat(undefined, {
    notation: value >= 10_000 ? "compact" : "standard",
    maximumFractionDigits: value >= 10_000 ? 1 : 0,
  }).format(value)
}

export function CreditsMeter() {
  const { state, isMobile } = useSidebar()
  const { data } = useQuery(creditBalanceQuery())
  if (!data) return null

  const total = data.allowance + data.granted
  const remaining = Math.max(0, data.remaining)
  const out = remaining <= 0
  const low = !out && total > 0 && remaining <= total * 0.1
  const collapsed = state === "collapsed" && !isMobile

  const tone = out
    ? "text-destructive"
    : low
      ? "text-warning-foreground"
      : "text-muted-foreground"

  const label = `${compact(remaining)} of ${compact(total)} credits left · renews ${new Date(
    data.renews_at,
  ).toLocaleDateString()}`

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <RouterLink
          to="/usage"
          search={{ from: undefined, to: undefined }}
          aria-label={label}
          data-testid="credits-meter"
          className={cn(
            "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition hover:bg-sidebar-accent",
            collapsed && "justify-center px-0",
            tone,
          )}
        >
          <Coins className="size-4 shrink-0" />
          {!collapsed && (
            <>
              <span className="font-mono tabular-nums">
                {compact(remaining)}
              </span>
              <span className="truncate opacity-70">credits left</span>
            </>
          )}
        </RouterLink>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}
