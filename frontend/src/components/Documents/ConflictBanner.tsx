import { AlertTriangle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import type { AutosaveConflict } from "@/hooks/useAutosave"

interface ConflictBannerProps {
  conflict: AutosaveConflict
  onReload: () => void
  onOverwrite: () => void
}

export function ConflictBanner({
  conflict,
  onReload,
  onOverwrite,
}: ConflictBannerProps) {
  return (
    <Alert
      className="border-warning/40 bg-warning/10"
      data-testid="conflict-banner"
    >
      <AlertTriangle className="size-4" />
      <AlertTitle>Someone else updated this page</AlertTitle>
      <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span>
          {conflict.message}
          {conflict.serverVersion != null &&
            ` Server has version ${conflict.serverVersion}.`}{" "}
          Reload to see their changes (your edits are lost) or overwrite with
          yours.
        </span>
        <span className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={onReload}>
            Reload latest
          </Button>
          <Button size="sm" onClick={onOverwrite}>
            Overwrite
          </Button>
        </span>
      </AlertDescription>
    </Alert>
  )
}

export default ConflictBanner
