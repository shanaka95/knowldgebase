import { format, startOfMonth, subDays } from "date-fns"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { Range } from "@/queries/usage"

/**
 * The days a dashboard is showing.
 *
 * Presets rather than a calendar: "the last 30 days" is what anybody actually
 * wants, and a calendar component would mean a second dependency for a control
 * used on two screens. The two date boxes below cover the rest, and a native
 * date input already gives a picker on every platform we support.
 */

const PRESETS = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
] as const

const iso = (d: Date) => format(d, "yyyy-MM-dd")

export function today(): string {
  return iso(new Date())
}

export function lastDays(days: number): Range {
  return { from: iso(subDays(new Date(), days - 1)), to: today() }
}

export function thisMonth(): Range {
  return { from: iso(startOfMonth(new Date())), to: today() }
}

/** The range a screen opens on, and what an absent URL parameter means. */
export const DEFAULT_RANGE_DAYS = 30

export function RangePicker({
  value,
  onChange,
  className,
}: {
  value: Range
  onChange: (range: Range) => void
  className?: string
}) {
  const matches = (days: number) => {
    const preset = lastDays(days)
    return preset.from === value.from && preset.to === value.to
  }
  const month = thisMonth()
  const isMonth = month.from === value.from && month.to === value.to

  return (
    <div
      className={cn("flex flex-wrap items-center gap-2", className)}
      data-testid="range-picker"
    >
      {PRESETS.map((preset) => (
        <Button
          key={preset.days}
          size="sm"
          variant={matches(preset.days) ? "secondary" : "ghost"}
          onClick={() => onChange(lastDays(preset.days))}
          data-testid={`range-${preset.days}`}
        >
          {preset.label}
        </Button>
      ))}
      <Button
        size="sm"
        variant={isMonth ? "secondary" : "ghost"}
        onClick={() => onChange(thisMonth())}
        data-testid="range-month"
      >
        This month
      </Button>
      <span className="flex items-center gap-1.5">
        <Input
          type="date"
          value={value.from}
          max={value.to}
          onChange={(e) =>
            e.target.value && onChange({ ...value, from: e.target.value })
          }
          className="h-8 w-[9.5rem]"
          aria-label="From"
          data-testid="range-from"
        />
        <span className="text-muted-foreground text-sm">to</span>
        <Input
          type="date"
          value={value.to}
          min={value.from}
          max={today()}
          onChange={(e) =>
            e.target.value && onChange({ ...value, to: e.target.value })
          }
          className="h-8 w-[9.5rem]"
          aria-label="To"
          data-testid="range-to"
        />
      </span>
    </div>
  )
}
