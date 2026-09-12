import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { EmbeddingState } from "@/lib/embeddingState"
import { cn } from "@/lib/utils"
import { EMBEDDING_STATE_META } from "./embeddingStateMeta"

interface EmbeddingStatusPillProps {
  state: EmbeddingState
  /** 0–100 while embedding; shown as a tiny bar. */
  progress?: number | null
  /** e.g. "attempt 2/3" or the error excerpt for the tooltip. */
  detail?: string | null
  attempts?: number | null
  maxAttempts?: number | null
  chunkCount?: number | null
  chunkingMethod?: string | null
  updatedAt?: string | Date | null
  onClick?: () => void
  className?: string
  size?: "sm" | "md"
}

export function EmbeddingStatusPill({
  state,
  progress,
  detail,
  attempts,
  maxAttempts,
  chunkCount,
  chunkingMethod,
  updatedAt,
  onClick,
  className,
  size = "md",
}: EmbeddingStatusPillProps) {
  const meta = EMBEDDING_STATE_META[state]
  const Icon = meta.icon
  const showProgress = state === "embedding" && progress != null && progress > 0

  const badge = (
    <Badge
      asChild={Boolean(onClick)}
      variant="outline"
      className={cn(
        "gap-1.5 rounded-full font-medium",
        size === "sm" ? "h-5 px-2 text-[11px]" : "h-6 px-2.5 text-xs",
        meta.badgeClass,
        onClick &&
          "cursor-pointer hover:brightness-95 dark:hover:brightness-110",
        className,
      )}
      data-testid="embedding-status-pill"
      data-state={state}
    >
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          aria-label={`AI index: ${meta.label}`}
        >
          <PillContent
            Icon={Icon}
            spinner={meta.spinner}
            label={meta.label}
            progress={showProgress ? progress : null}
            attempts={attempts}
            maxAttempts={maxAttempts}
            state={state}
          />
        </button>
      ) : (
        <PillContent
          Icon={Icon}
          spinner={meta.spinner}
          label={meta.label}
          progress={showProgress ? progress : null}
          attempts={attempts}
          maxAttempts={maxAttempts}
          state={state}
        />
      )}
    </Badge>
  )

  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <p className="font-medium">{meta.label}</p>
        <p className="text-xs opacity-80">{detail ?? meta.description}</p>
        {(chunkCount != null || chunkingMethod || updatedAt) && (
          <p className="mt-1 text-[11px] opacity-70">
            {chunkCount != null && (
              <>
                {chunkCount} chunk{chunkCount === 1 ? "" : "s"}
              </>
            )}
            {chunkingMethod && <> · {chunkingMethod.replace(/_/g, " ")}</>}
            {updatedAt && <> · {new Date(updatedAt).toLocaleString()}</>}
          </p>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

function PillContent({
  Icon,
  spinner,
  label,
  progress,
  attempts,
  maxAttempts,
  state,
}: {
  Icon: React.ComponentType<{ className?: string }>
  spinner: boolean
  label: string
  progress: number | null
  attempts?: number | null
  maxAttempts?: number | null
  state: EmbeddingState
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {spinner ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : (
        <Icon className="size-3.5" />
      )}
      <span>{label}</span>
      {state === "pending" &&
        attempts != null &&
        maxAttempts != null &&
        attempts > 0 && (
          <span className="opacity-70">
            · retry {attempts}/{maxAttempts}
          </span>
        )}
      {progress != null && (
        <span className="inline-flex items-center gap-1">
          <Progress value={progress} className="h-1 w-10 bg-current/20" />
          <span className="tabular-nums opacity-80">
            {Math.round(progress)}%
          </span>
        </span>
      )}
    </span>
  )
}

export default EmbeddingStatusPill
