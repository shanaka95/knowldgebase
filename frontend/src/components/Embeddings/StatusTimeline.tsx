import { Ban, Check, Loader2, X } from "lucide-react"

import type { EmbeddingJobPublic } from "@/client"
import type { EmbeddingState } from "@/lib/embeddingState"
import { cn } from "@/lib/utils"

const STEPS = [
  { key: "pending", label: "Queued" },
  { key: "chunking", label: "Chunking" },
  { key: "summarizing", label: "Summarizing" },
  { key: "embedding", label: "Embedding" },
  { key: "ready", label: "Indexed" },
] as const

type StepKey = (typeof STEPS)[number]["key"]

function stepIndex(state: EmbeddingState, job: EmbeddingJobPublic | null) {
  if (state === "ready" || state === "stale") return STEPS.length - 1
  if (state === "failed") {
    // fail at the stage the last job reached
    const stage = job?.stage
    if (stage === "chunking") return 1
    if (stage === "summarizing") return 2
    if (stage === "embedding" || stage === "writing") return 3
    return 0
  }
  const idx = STEPS.findIndex((s) => s.key === state)
  return idx === -1 ? -1 : idx
}

interface StatusTimelineProps {
  state: EmbeddingState
  job: EmbeddingJobPublic | null
  className?: string
}

/** Horizontal step indicator: pending → chunking → summarizing → embedding → indexed. */
export function StatusTimeline({ state, job, className }: StatusTimelineProps) {
  const current = stepIndex(state, job)
  const failed = state === "failed"
  const cancelled = job?.status === "cancelled" && state !== "ready"

  return (
    <ol
      className={cn("flex items-center gap-1", className)}
      aria-label="Indexing progress"
      data-testid="status-timeline"
    >
      {STEPS.map((step, i) => {
        const done = current > i || state === "ready" || state === "stale"
        const active = current === i && !done
        const isFailedHere = failed && current === i
        return (
          <li
            key={step.key}
            className="flex flex-1 items-center gap-1 last:flex-none"
          >
            <div className="flex flex-col items-center gap-1">
              <span
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-[11px] transition-colors",
                  done && "border-success bg-success text-success-foreground",
                  active &&
                    !isFailedHere &&
                    "border-primary bg-primary/10 text-primary",
                  isFailedHere &&
                    "border-destructive bg-destructive/10 text-destructive",
                  !done && !active && "border-border text-muted-foreground",
                )}
                data-step={step.key satisfies StepKey}
                data-active={active || undefined}
              >
                {isFailedHere ? (
                  cancelled ? (
                    <Ban className="size-3" />
                  ) : (
                    <X className="size-3" />
                  )
                ) : done ? (
                  <Check className="size-3" />
                ) : active ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <span>{i + 1}</span>
                )}
              </span>
              <span
                className={cn(
                  "text-[10px] leading-none",
                  active || isFailedHere
                    ? "font-medium text-foreground"
                    : "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span
                className={cn(
                  "mb-4 h-px flex-1",
                  current > i ? "bg-success" : "bg-border",
                )}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}

export default StatusTimeline
