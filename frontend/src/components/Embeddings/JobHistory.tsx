import { format, formatDistanceToNowStrict } from "date-fns"
import { History } from "lucide-react"

import type { EmbeddingJobPublic } from "@/client"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { JOB_STAGE_LABELS, JOB_STATUS_LABELS } from "./chunkingMethodLabels"

const STATUS_CLASS: Record<string, string> = {
  queued: "border-border bg-muted text-muted-foreground",
  running: "border-primary/30 bg-primary/10 text-primary",
  succeeded: "border-success/30 bg-success/10 text-success",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
  cancelled: "border-border bg-muted text-muted-foreground",
  superseded: "border-border bg-muted text-muted-foreground",
}

const STAGE_ORDER = [
  "loading",
  "chunking",
  "summarizing",
  "embedding",
  "writing",
]

function durationLabel(job: EmbeddingJobPublic): string | null {
  if (!job.started_at) return null
  const end = job.finished_at ? new Date(job.finished_at) : new Date()
  const seconds = Math.max(
    0,
    Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000),
  )
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function relative(iso: string | null | undefined): string {
  if (!iso) return "-"
  return `${formatDistanceToNowStrict(new Date(iso))} ago`
}

function StageBars({
  stats,
}: {
  stats: Record<string, unknown> | null | undefined
}) {
  const stageMs = (stats?.stage_ms ?? null) as Record<string, number> | null
  if (!stageMs) return null
  const entries = STAGE_ORDER.filter((k) => typeof stageMs[k] === "number").map(
    (k) => [k, stageMs[k]] as const,
  )
  const total = entries.reduce((acc, [, ms]) => acc + ms, 0)
  if (total <= 0) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          role="img"
          className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-muted"
          aria-label="Time per stage"
        >
          {entries.map(([k, ms]) => (
            <span
              key={k}
              className={cn(
                "h-full",
                k === "chunking" && "bg-info",
                k === "summarizing" && "bg-violet-500",
                k === "embedding" && "bg-primary",
                (k === "loading" || k === "writing") &&
                  "bg-muted-foreground/50",
              )}
              style={{ width: `${(ms / total) * 100}%` }}
            />
          ))}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        {entries.map(([k, ms]) => (
          <div key={k} className="flex justify-between gap-4">
            <span>{JOB_STAGE_LABELS[k] ?? k}</span>
            <span className="tabular-nums">{(ms / 1000).toFixed(1)}s</span>
          </div>
        ))}
      </TooltipContent>
    </Tooltip>
  )
}

interface JobHistoryProps {
  jobs: EmbeddingJobPublic[]
}

export function JobHistory({ jobs }: JobHistoryProps) {
  return (
    <section
      className="rounded-lg border bg-card p-3"
      aria-labelledby="ai-jobs-heading"
      data-testid="ai-job-history"
    >
      <h4
        id="ai-jobs-heading"
        className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"
      >
        <History className="size-3.5" />
        Job history
      </h4>
      {jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No indexing jobs yet.</p>
      ) : (
        <ul className="flex flex-col divide-y">
          {jobs.map((job) => {
            const duration = durationLabel(job)
            const stageLabel =
              job.status === "running" && job.stage
                ? (JOB_STAGE_LABELS[job.stage] ?? job.stage)
                : job.status === "cancelled" && job.stage
                  ? `stopped while ${(JOB_STAGE_LABELS[job.stage] ?? job.stage).toLowerCase()}`
                  : null
            return (
              <li
                key={job.id}
                className="py-2 text-xs"
                data-status={job.status}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant="outline"
                    className={cn(
                      "h-5 px-1.5 text-[10px]",
                      STATUS_CLASS[job.status],
                    )}
                  >
                    {JOB_STATUS_LABELS[job.status] ?? job.status}
                  </Badge>
                  <span className="text-muted-foreground">
                    v{job.doc_version}
                  </span>
                  {stageLabel && (
                    <span className="text-muted-foreground">
                      · {stageLabel}
                    </span>
                  )}
                  {(job.attempts ?? 0) > 0 && (
                    <span className="text-muted-foreground">
                      · attempt {job.attempts}/{job.max_attempts ?? 3}
                    </span>
                  )}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="ml-auto tabular-nums text-muted-foreground">
                        {relative(
                          job.finished_at ?? job.started_at ?? job.created_at,
                        )}
                        {duration && ` · ${duration}`}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent side="left" className="text-xs">
                      <div>
                        Queued:{" "}
                        {job.created_at
                          ? format(new Date(job.created_at), "PPpp")
                          : "-"}
                      </div>
                      <div>
                        Started:{" "}
                        {job.started_at
                          ? format(new Date(job.started_at), "PPpp")
                          : "-"}
                      </div>
                      <div>
                        Finished:{" "}
                        {job.finished_at
                          ? format(new Date(job.finished_at), "PPpp")
                          : "-"}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <StageBars stats={job.stats} />
                {job.error && job.status !== "succeeded" && (
                  <Alert variant="destructive" className="mt-2 px-2.5 py-2">
                    <AlertDescription>
                      <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug">
                        {job.error}
                      </pre>
                    </AlertDescription>
                  </Alert>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

export default JobHistory
