import { Loader2 } from "lucide-react"

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { EmbeddingState } from "@/lib/embeddingState"
import { cn } from "@/lib/utils"
import { EMBEDDING_STATE_META } from "./embeddingStateMeta"

interface EmbeddingStatusIconProps {
  state: EmbeddingState
  className?: string
  /** Hide when everything is fine to keep lists quiet. */
  hideWhenReady?: boolean
  withTooltip?: boolean
}

/** Compact indicator for trees and lists: spinner while running, amber for stale, red for failed. */
export function EmbeddingStatusIcon({
  state,
  className,
  hideWhenReady = true,
  withTooltip = true,
}: EmbeddingStatusIconProps) {
  if (hideWhenReady && (state === "ready" || state === "none")) return null
  const meta = EMBEDDING_STATE_META[state]
  const Icon = meta.icon
  const node = meta.spinner ? (
    <Loader2
      className={cn(
        "size-3.5 shrink-0 animate-spin",
        meta.iconClass,
        className,
      )}
      aria-label={meta.label}
      data-testid="embedding-status-icon"
      data-state={state}
    />
  ) : (
    <Icon
      className={cn("size-3.5 shrink-0", meta.iconClass, className)}
      aria-label={meta.label}
      data-testid="embedding-status-icon"
      data-state={state}
    />
  )
  if (!withTooltip) return node
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex">{node}</span>
      </TooltipTrigger>
      <TooltipContent side="right">{meta.label}</TooltipContent>
    </Tooltip>
  )
}

export function EmbeddingStatusDot({
  state,
  className,
}: {
  state: EmbeddingState
  className?: string
}) {
  if (state === "ready" || state === "none") return null
  const meta = EMBEDDING_STATE_META[state]
  return (
    <span
      role="img"
      className={cn(
        "inline-block size-1.5 shrink-0 rounded-full bg-current",
        meta.spinner && "animate-pulse",
        meta.iconClass,
        className,
      )}
      aria-label={meta.label}
      title={meta.label}
      data-state={state}
    />
  )
}

export default EmbeddingStatusIcon
