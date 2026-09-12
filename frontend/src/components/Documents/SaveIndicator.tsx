import { formatDistanceToNowStrict } from "date-fns"
import {
  AlertTriangle,
  Check,
  CloudOff,
  Loader2,
  RefreshCw,
  UploadCloud,
} from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import type { AutosaveStatus } from "@/hooks/useAutosave"
import { cn } from "@/lib/utils"

interface SaveIndicatorProps {
  status: AutosaveStatus
  lastSavedAt: Date | null
  error?: string | null
  onRetry?: () => void
  className?: string
}

function useTick(ms: number, active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick((t) => t + 1), ms)
    return () => clearInterval(id)
  }, [ms, active])
}

export function SaveIndicator({
  status,
  lastSavedAt,
  error,
  onRetry,
  className,
}: SaveIndicatorProps) {
  useTick(30_000, status === "saved" || status === "clean")

  const savedLabel = lastSavedAt
    ? `Saved · ${
        Date.now() - lastSavedAt.getTime() < 45_000
          ? "just now"
          : `${formatDistanceToNowStrict(lastSavedAt)} ago`
      }`
    : "Saved"

  const base = "inline-flex items-center gap-1.5 text-xs"

  switch (status) {
    case "dirty":
      return (
        <span
          className={cn(base, "text-muted-foreground", className)}
          data-testid="save-indicator"
          data-status={status}
        >
          <span className="size-1.5 rounded-full bg-warning" />
          Unsaved changes
        </span>
      )
    case "saving":
      return (
        <span
          className={cn(base, "text-muted-foreground", className)}
          data-testid="save-indicator"
          data-status={status}
        >
          <Loader2 className="size-3.5 animate-spin" />
          Saving…
        </span>
      )
    case "blocked":
      return (
        <span
          className={cn(base, "text-muted-foreground", className)}
          data-testid="save-indicator"
          data-status={status}
        >
          <UploadCloud className="size-3.5 animate-pulse" />
          Waiting for uploads…
        </span>
      )
    case "error":
      return (
        <span
          className={cn(base, "text-destructive", className)}
          data-testid="save-indicator"
          data-status={status}
        >
          <CloudOff className="size-3.5" />
          <span title={error ?? undefined}>Couldn't save</span>
          {onRetry && (
            <Button
              size="xs"
              variant="outline"
              onClick={onRetry}
              className="h-6 px-2"
            >
              <RefreshCw className="size-3" />
              Retry
            </Button>
          )}
        </span>
      )
    case "conflict":
      return (
        <span
          className={cn(
            base,
            "text-warning-foreground dark:text-warning",
            className,
          )}
          data-testid="save-indicator"
          data-status={status}
        >
          <AlertTriangle className="size-3.5" />
          Conflict
        </span>
      )
    default:
      return (
        <span
          className={cn(base, "text-muted-foreground", className)}
          data-testid="save-indicator"
          data-status={status}
        >
          <Check className="size-3.5 text-success" />
          {savedLabel}
        </span>
      )
  }
}

export default SaveIndicator
