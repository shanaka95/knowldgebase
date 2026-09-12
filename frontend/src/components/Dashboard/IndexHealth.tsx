import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { embeddingSummaryQuery, healthQuery } from "@/queries/system"

const SERVICE_LABELS: Record<string, string> = {
  db: "Database",
  qdrant: "Qdrant",
  minio: "Storage",
  embedding: "Embeddings",
  llm: "LLM",
  worker: "Worker",
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "muted" | "info" | "success" | "warning" | "destructive"
}) {
  const tones = {
    muted: "text-muted-foreground",
    info: "text-info",
    success: "text-success",
    warning: "text-warning-foreground dark:text-warning",
    destructive: "text-destructive",
  }
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p
        className={cn("mt-1 text-2xl font-semibold tabular-nums", tones[tone])}
      >
        {value}
      </p>
    </div>
  )
}

export function WorkerBanner() {
  const { data } = useQuery(healthQuery())
  if (data?.services.worker?.ok !== false) return null
  return (
    <Alert
      className="border-warning/50 bg-warning/10"
      data-testid="worker-banner"
    >
      <AlertTriangle className="text-warning-foreground dark:text-warning" />
      <AlertTitle>Indexing worker offline</AlertTitle>
      <AlertDescription>
        New and edited pages are queued and will be indexed as soon as the
        worker is back.
      </AlertDescription>
    </Alert>
  )
}

export function IndexHealth() {
  const summary = useQuery(embeddingSummaryQuery())
  const health = useQuery(healthQuery())

  if (summary.isPending) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-20 w-full" />
        ))}
      </div>
    )
  }
  const s = summary.data
  return (
    <div className="flex flex-col gap-3" data-testid="index-health">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Tile label="Pages" value={s?.total ?? 0} tone="muted" />
        <Tile label="Indexed" value={s?.ready ?? 0} tone="success" />
        <Tile
          label="In progress"
          value={(s?.in_progress ?? 0) + (s?.pending ?? 0)}
          tone="info"
        />
        <Tile label="Stale" value={s?.stale ?? 0} tone="warning" />
        <Tile label="Failed" value={s?.failed ?? 0} tone="destructive" />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {health.isPending && (
          <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
        )}
        {health.data &&
          Object.entries(health.data.services).map(([key, svc]) => (
            <span
              key={key}
              title={svc.detail ?? undefined}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
                svc.ok
                  ? "border-success/30 bg-success/10 text-success"
                  : "border-destructive/30 bg-destructive/10 text-destructive",
              )}
              data-testid={`service-${key}`}
            >
              {svc.ok ? (
                <CheckCircle2 className="size-3" />
              ) : (
                <XCircle className="size-3" />
              )}
              {SERVICE_LABELS[key] ?? key}
            </span>
          ))}
        {health.isError && (
          <span className="text-destructive">Health endpoint unreachable</span>
        )}
        {s && (s.queued_jobs || s.running_jobs) ? (
          <span className="text-muted-foreground">
            · {s.running_jobs ?? 0} running, {s.queued_jobs ?? 0} queued
          </span>
        ) : null}
      </div>
    </div>
  )
}
