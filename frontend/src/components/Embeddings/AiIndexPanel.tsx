import { useQuery } from "@tanstack/react-query"
import { formatDistanceToNowStrict } from "date-fns"
import {
  BrainCircuit,
  RefreshCw,
  RotateCcw,
  Sparkles,
  WifiOff,
  X,
} from "lucide-react"

import { HealthService } from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { useDocumentMutations } from "@/hooks/useDocumentMutations"
import { useEmbeddingStatus } from "@/hooks/useEmbeddingStatus"
import { queryKeys } from "@/lib/queryKeys"
import { ChunkList } from "./ChunkList"
import { chunkingMethodLabel } from "./chunkingMethodLabels"
import { EmbeddingStatusPill } from "./EmbeddingStatusPill"
import { EMBEDDING_STATE_META } from "./embeddingStateMeta"
import { JobHistory } from "./JobHistory"
import { StatusTimeline } from "./StatusTimeline"
import { SummaryCard } from "./SummaryCard"

interface AiIndexPanelProps {
  documentId: string
  namespaceId: string
  namespaceSlug?: string | null
  canEdit: boolean
  onClose?: () => void
}

function useWorkerOnline(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: async () => (await HealthService.readHealth()).data,
    enabled,
    staleTime: 20_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: false,
  })
}

/** Right-rail panel: pipeline status, summary, chunks, job history and actions. */
export function AiIndexPanel({
  documentId,
  namespaceId,
  namespaceSlug,
  canEdit,
  onClose,
}: AiIndexPanelProps) {
  const status = useEmbeddingStatus(documentId, namespaceId)
  const { regenerate } = useDocumentMutations({
    id: documentId,
    namespace_id: namespaceId,
    namespace_slug: namespaceSlug,
  })
  const health = useWorkerOnline(true)
  const workerOffline = health.data
    ? health.data.services.worker?.ok === false
    : false

  const data = status.data
  const state = status.state
  const meta = EMBEDDING_STATE_META[state]
  const busy = status.inProgress || regenerate.isPending

  const action: "generate" | "retry" | "regenerate" | null =
    state === "none"
      ? "generate"
      : state === "failed"
        ? "retry"
        : state === "ready" || state === "stale"
          ? "regenerate"
          : null

  return (
    <div
      className="flex h-full flex-col gap-3"
      data-testid="ai-index-panel"
      data-state={state}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <BrainCircuit className="size-4 text-primary" />
            AI index
          </h3>
          <p className="text-xs text-muted-foreground">{meta.description}</p>
        </div>
        {onClose && (
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={onClose}
            aria-label="Close AI index panel"
          >
            <X className="size-4" />
          </Button>
        )}
      </header>

      {status.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <EmbeddingStatusPill
              state={state}
              progress={status.progress}
              attempts={data.embedding_attempts}
              maxAttempts={data.current_job?.max_attempts ?? 3}
              detail={data.embedding_error ?? undefined}
            />
            {data.is_stale && state !== "failed" && (
              <span className="text-[11px] text-muted-foreground">
                indexed v{data.embedding_version ?? "-"} · current v
                {data.version}
              </span>
            )}
          </div>

          <StatusTimeline
            state={state}
            job={data.current_job ?? data.jobs?.[0] ?? null}
          />

          {workerOffline && (
            <Alert className="border-warning/40 bg-warning/10">
              <WifiOff className="size-4" />
              <AlertTitle>Indexing worker offline</AlertTitle>
              <AlertDescription>
                Jobs stay queued until a worker comes back. Start it with{" "}
                <code className="font-mono text-[11px]">
                  docker compose up worker
                </code>
                .
              </AlertDescription>
            </Alert>
          )}

          {state === "failed" && data.embedding_error && (
            <Alert variant="destructive">
              <AlertTitle>Indexing failed</AlertTitle>
              <AlertDescription>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-snug">
                  {data.embedding_error}
                </pre>
              </AlertDescription>
            </Alert>
          )}

          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 rounded-lg border bg-card p-3 text-xs">
            <Detail
              label="Method"
              value={chunkingMethodLabel(data.chunking_method)}
            />
            <Detail
              label="Chunks"
              value={
                data.embedding_version != null
                  ? String(data.chunk_count ?? 0)
                  : "-"
              }
            />
            <Detail
              label="Attempts"
              value={`${data.embedding_attempts ?? 0} / ${data.current_job?.max_attempts ?? 3}`}
            />
            <Detail
              label="Version"
              value={
                data.embedding_version != null
                  ? `${data.version} (indexed ${data.embedding_version})`
                  : `${data.version} (not indexed)`
              }
            />
            <Detail
              label="Indexed"
              value={
                data.embedding_updated_at
                  ? `${formatDistanceToNowStrict(new Date(data.embedding_updated_at))} ago`
                  : "never"
              }
              title={
                data.embedding_updated_at
                  ? new Date(data.embedding_updated_at).toLocaleString()
                  : undefined
              }
            />
            <Detail
              label="Vectors"
              value={
                data.embedding_version != null
                  ? `${2 + (data.chunk_count ?? 0)} (page, summary, chunks)`
                  : "-"
              }
            />
          </dl>

          <SummaryCard
            summary={data.summary}
            loading={status.inProgress && !data.summary}
          />
          <ChunkList chunks={data.chunks ?? []} method={data.chunking_method} />
          <JobHistory jobs={data.jobs ?? []} />
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Couldn't load the index status.
        </p>
      )}

      {canEdit && action && (
        <footer className="mt-auto flex items-center gap-2 border-t pt-3">
          {action === "regenerate" ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  data-testid="ai-regenerate"
                >
                  <RefreshCw className="size-3.5" />
                  Regenerate
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Regenerate the index?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The page will be re-chunked, re-summarised and re-embedded.
                    Existing vectors are replaced once the new ones are ready.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => regenerate.mutate()}>
                    Regenerate
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <LoadingButton
              size="sm"
              variant={action === "retry" ? "destructive" : "default"}
              loading={regenerate.isPending}
              disabled={busy}
              onClick={() => regenerate.mutate()}
              data-testid={action === "retry" ? "ai-retry" : "ai-generate"}
            >
              {action === "retry" ? (
                <RotateCcw className="size-3.5" />
              ) : (
                <Sparkles className="size-3.5" />
              )}
              {action === "retry" ? "Retry" : "Generate embeddings"}
            </LoadingButton>
          )}
          {busy && (
            <span className="text-xs text-muted-foreground">
              Working… you can keep editing.
            </span>
          )}
        </footer>
      )}
    </div>
  )
}

function Detail({
  label,
  value,
  title,
}: {
  label: string
  value: string
  title?: string
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="truncate font-medium" title={title ?? value}>
        {value}
      </dd>
    </div>
  )
}

export default AiIndexPanel
