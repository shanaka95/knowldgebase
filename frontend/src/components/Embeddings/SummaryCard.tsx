import { Sparkles } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"

interface SummaryCardProps {
  summary: string | null | undefined
  loading?: boolean
}

export function SummaryCard({ summary, loading }: SummaryCardProps) {
  return (
    <section
      className="rounded-lg border bg-card p-3"
      aria-labelledby="ai-summary-heading"
      data-testid="ai-summary"
    >
      <h4
        id="ai-summary-heading"
        className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"
      >
        <Sparkles className="size-3.5" />
        Summary
      </h4>
      {loading ? (
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-11/12" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ) : summary ? (
        <p className="text-sm leading-relaxed text-foreground/90">{summary}</p>
      ) : (
        <p className="text-sm text-muted-foreground">
          No summary yet. It is written when the page is indexed.
        </p>
      )}
    </section>
  )
}

export default SummaryCard
