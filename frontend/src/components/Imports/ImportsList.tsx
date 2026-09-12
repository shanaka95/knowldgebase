import { Link } from "@tanstack/react-router"
import {
  AlertCircle,
  ExternalLink,
  FileText,
  FileUp,
  ImageIcon,
  MoreHorizontal,
  RotateCcw,
  Trash2,
  XCircle,
} from "lucide-react"
import { useState } from "react"

import type { ImportJobPublic } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  useCancelImport,
  useDeleteImport,
  useRetryImport,
} from "@/hooks/useImports"
import { relativeTime } from "@/lib/format"
import { isImportActive } from "@/queries/imports"
import { openDialog } from "@/stores/dialogs"
import { formatBytes, isPdf } from "./fileHelpers"
import { ImportStatusPill } from "./ImportStatusPill"
import { PARSER_DESCRIPTIONS, PARSER_LABELS } from "./importStatusMeta"

function ParserBadge({ parser }: { parser: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="secondary" className="h-5 px-1.5 text-[11px]">
          {PARSER_LABELS[parser] ?? parser}
        </Badge>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        {PARSER_DESCRIPTIONS[parser] ?? parser}
      </TooltipContent>
    </Tooltip>
  )
}

function ImportRow({ job }: { job: ImportJobPublic }) {
  const retry = useRetryImport()
  const cancel = useCancelImport()
  const remove = useDeleteImport()
  const [confirmDelete, setConfirmDelete] = useState(false)

  const active = isImportActive(job)
  const canRetry = job.status === "failed" || job.status === "cancelled"
  // the API defaults these, so the generated types make them optional
  const pagesTotal = job.pages_total ?? 0
  const pagesDone = job.pages_done ?? 0
  const attempts = job.attempts ?? 0
  const progress = pagesTotal > 0 ? (pagesDone / pagesTotal) * 100 : 0

  return (
    <li className="flex flex-col gap-2 px-4 py-3" data-testid="import-row">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          {isPdf({ type: job.content_type, name: job.filename }) ? (
            <FileText className="size-4" />
          ) : (
            <ImageIcon className="size-4" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 truncate text-sm font-medium">
              {job.title || job.filename}
            </span>
            <ImportStatusPill job={job} />
            {job.parser && <ParserBadge parser={job.parser} />}
            {attempts > 0 && job.status !== "done" && (
              <span className="text-xs text-muted-foreground">
                attempt {attempts}/{job.max_attempts ?? 3}
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {job.filename} · {formatBytes(job.size)}
            {job.namespace_slug && <> · {job.namespace_slug}</>}
            {job.created_at && <> · {relativeTime(job.created_at)}</>}
          </p>
          {job.status === "parsing" && pagesTotal > 0 && (
            <Progress
              value={progress}
              className="mt-2 h-1 w-full max-w-xs"
              aria-label={`Parsed ${pagesDone} of ${pagesTotal} pages`}
            />
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {job.document_id && job.namespace_slug && (
            <Button asChild variant="outline" size="xs">
              <Link
                to="/s/$namespaceSlug/d/$documentId"
                params={{
                  namespaceSlug: job.namespace_slug,
                  documentId: job.document_id,
                }}
                search={{ mode: "view" } as never}
                data-testid="import-open-page"
              >
                <ExternalLink className="size-3.5" />
                Open page
              </Link>
            </Button>
          )}
          {canRetry && (
            <Button
              variant="outline"
              size="xs"
              disabled={retry.isPending}
              onClick={() => retry.mutate(job.id)}
              data-testid="import-retry"
            >
              <RotateCcw className="size-3.5" />
              Retry
            </Button>
          )}
          {active && (
            <Button
              variant="ghost"
              size="xs"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate(job.id)}
              data-testid="import-cancel"
            >
              <XCircle className="size-3.5" />
              Cancel
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Import actions"
                data-testid="import-actions"
              >
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                variant="destructive"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 className="size-4" />
                Remove from list
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {job.status === "failed" && job.error && (
        <Alert variant="destructive" className="ml-12">
          <AlertCircle />
          <AlertDescription className="text-xs">{job.error}</AlertDescription>
        </Alert>
      )}

      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove this import?</AlertDialogTitle>
            <AlertDialogDescription>
              {job.document_id
                ? "The page it created and the attached original file are kept — only this record is removed."
                : "The uploaded file is discarded. This cannot be undone."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => remove.mutate(job)}
              data-testid="import-delete-confirm"
            >
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  )
}

export function ImportsListSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-9 rounded-md" />
          <div className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function ImportsList({ jobs }: { jobs: ImportJobPublic[] }) {
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={FileUp}
        title="No imports yet"
        description="Upload a PDF or an image and it becomes an editable page, with the original file kept alongside it."
        action={
          <Button
            onClick={() => openDialog({ kind: "import" })}
            data-testid="import-empty-cta"
          >
            <FileUp />
            Import a file
          </Button>
        }
      />
    )
  }

  return (
    <ul className="divide-y rounded-lg border" data-testid="imports-list">
      {jobs.map((job) => (
        <ImportRow key={job.id} job={job} />
      ))}
    </ul>
  )
}
