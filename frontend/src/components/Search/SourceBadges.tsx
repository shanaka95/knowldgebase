import type { RetrievalSourceHit } from "@/client"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { methodMeta, targetLabel } from "@/lib/searchPrefs"
import { cn } from "@/lib/utils"

/**
 * The "why did this match" row: one badge per source that ranked the page,
 * colour-coded by method and ordered by how much it contributed.
 */
export function SourceBadges({
  sources,
  className,
}: {
  sources: RetrievalSourceHit[]
  className?: string
}) {
  if (sources.length === 0) return null
  return (
    <span className={cn("flex flex-wrap items-center gap-1", className)}>
      {sources.map((s) => {
        const meta = methodMeta(s.method)
        return (
          <Tooltip key={`${s.method}-${s.target}-${s.rank}`}>
            <TooltipTrigger asChild>
              <Badge
                variant="outline"
                className={cn("gap-1 font-normal", meta.badge)}
                data-testid="source-badge"
              >
                <span
                  className={cn("size-1.5 rounded-full", meta.dot)}
                  aria-hidden
                />
                {meta.label}
                <span className="opacity-60">·</span>
                {targetLabel(s.target).toLowerCase()}
                <span className="font-mono opacity-70">#{s.rank}</span>
              </Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              <p className="font-medium">
                {meta.label} ({meta.sublabel}) matched the{" "}
                {targetLabel(s.target).toLowerCase()}
              </p>
              <p className="mt-1 text-muted-foreground">
                Ranked #{s.rank} there, raw score {s.score.toFixed(4)}, adding{" "}
                {s.contribution.toFixed(5)} to the fused score.
              </p>
              {s.chunk_title && s.target === "chunk" && (
                <p className="mt-1 text-muted-foreground">
                  Section: “{s.chunk_title}”
                </p>
              )}
            </TooltipContent>
          </Tooltip>
        )
      })}
    </span>
  )
}

/** Right-aligned fused score with an explanation of how it was produced. */
export function FusedScore({ score, k }: { score: number; k: number }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="shrink-0 cursor-default font-mono text-xs text-muted-foreground tabular-nums"
          data-testid="fused-score"
        >
          {score.toFixed(3)}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">Fused score {score.toFixed(5)}</p>
        <p className="mt-1 text-muted-foreground">
          Reciprocal Rank Fusion: every source contributes 1 / (k + its rank),
          with k = {k}. Scores from different methods are not comparable, so the
          ranks are combined instead and pages several sources agree on win.
        </p>
      </TooltipContent>
    </Tooltip>
  )
}
