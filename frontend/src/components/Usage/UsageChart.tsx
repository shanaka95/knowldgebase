import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import { axisDate, compactNumber } from "@/lib/format"

/**
 * Activity over the range, stacked by whatever the caller splits it by.
 *
 * Stacked rather than grouped because the question is "how much, and what of" —
 * the total height is the figure people look at first, and the bands say where
 * it came from.
 */

export type ChartRow = { day: string } & Record<string, number | string>

export function UsageChart({
  rows,
  config,
  height = 240,
  formatValue = compactNumber,
}: {
  rows: ChartRow[]
  config: ChartConfig
  height?: number
  formatValue?: (value: number) => string
}) {
  const keys = Object.keys(config)
  return (
    <ChartContainer
      config={config}
      className="w-full"
      style={{ height }}
      data-testid="usage-chart"
    >
      <AreaChart data={rows} margin={{ left: 4, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis
          dataKey="day"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
          tickFormatter={(value: string) => axisDate(value)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={48}
          tickFormatter={(value: number) => formatValue(value)}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(label) => axisDate(String(label))}
              formatter={(value, name) => (
                <span className="flex w-full items-center justify-between gap-3">
                  <span className="text-muted-foreground">
                    {config[name as string]?.label ?? name}
                  </span>
                  <span className="font-mono tabular-nums">
                    {formatValue(Number(value))}
                  </span>
                </span>
              )}
            />
          }
        />
        {keys.length > 1 && <ChartLegend content={<ChartLegendContent />} />}
        {keys.map((key) => (
          <Area
            key={key}
            dataKey={key}
            type="monotone"
            stackId="a"
            stroke={`var(--color-${key})`}
            fill={`var(--color-${key})`}
            fillOpacity={0.2}
            strokeWidth={2}
          />
        ))}
      </AreaChart>
    </ChartContainer>
  )
}

/** Chart colours, cycled. shadcn defines five; a sixth feature reuses the first. */
export function chartConfig(
  entries: { key: string; label: string }[],
): ChartConfig {
  return Object.fromEntries(
    entries.map(({ key, label }, index) => [
      key,
      { label, color: `var(--chart-${(index % 5) + 1})` },
    ]),
  )
}
