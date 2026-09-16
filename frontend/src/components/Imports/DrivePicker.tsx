import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { ExternalLink, FileText, Loader2, Plus, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { DataSourcesService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  MAX_FILE_MB,
  type PickedFile,
  pickFromGoogleDrive,
  tooLarge,
} from "@/hooks/useGooglePicker"
import { queryKeys } from "@/lib/queryKeys"

/**
 * Choosing files from Drive instead of uploading them.
 *
 * Google's own chooser is the whole interface — there is no PlusGPT-built
 * Drive browser, because the `drive.file` scope grants nothing until somebody
 * picks something there. That is the consent, and building a browser would
 * both need a wider scope and be a second thing to maintain.
 *
 * Size is checked here as well as on the server, because the picker already
 * knows it: a 200MB file is refused the moment it is chosen rather than after
 * the server has fetched it from Google to find out.
 */

export function driveConnectedQuery() {
  return {
    queryKey: queryKeys.dataSources.all,
    queryFn: async () => (await DataSourcesService.readDataSources()).data,
    staleTime: 60_000,
  }
}

export function useDriveConnected() {
  const { data, isPending } = useQuery(driveConnectedQuery())
  const drive = (data?.data ?? []).find((s) => s.source_type === "google_drive")
  return {
    loading: isPending,
    available: Boolean(drive?.available),
    connected: Boolean(drive?.connected),
  }
}

function megabytes(bytes: number): string {
  if (!bytes) return ""
  const mb = bytes / (1024 * 1024)
  return mb < 0.1 ? "<0.1 MB" : `${mb.toFixed(1)} MB`
}

export function DrivePicker({
  files,
  onChange,
  disabled,
}: {
  files: PickedFile[]
  onChange: (files: PickedFile[]) => void
  disabled?: boolean
}) {
  const [opening, setOpening] = useState(false)

  const pick = async () => {
    setOpening(true)
    try {
      const picked = await pickFromGoogleDrive()
      if (picked.length === 0) return // cancelled, which is not a failure

      const oversized = tooLarge(picked)
      if (oversized.length > 0) {
        toast.error(
          oversized.length === 1
            ? `“${oversized[0].name}” is ${megabytes(oversized[0].size)}. The most a file may be is ${MAX_FILE_MB} MB.`
            : `${oversized.length} files are over ${MAX_FILE_MB} MB and were left out.`,
        )
      }
      const keep = picked.filter((f) => !oversized.includes(f))
      // Picking again adds to the selection rather than replacing it, so a
      // person can gather files from several folders in turn.
      const byId = new Map(files.map((f) => [f.file_id, f]))
      for (const f of keep) byId.set(f.file_id, f)
      onChange([...byId.values()])
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Google's file picker could not be opened.",
      )
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {files.length > 0 && (
        <ul className="flex flex-col gap-1.5" data-testid="drive-picked">
          {files.map((file) => (
            <li
              key={file.file_id}
              className="flex items-center gap-2 rounded-md border bg-muted/20 px-2.5 py-2 text-sm"
            >
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{file.name}</span>
              {file.size > 0 && (
                <span className="shrink-0 font-mono text-muted-foreground text-xs tabular-nums">
                  {megabytes(file.size)}
                </span>
              )}
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${file.name}`}
                disabled={disabled}
                onClick={() =>
                  onChange(files.filter((f) => f.file_id !== file.file_id))
                }
              >
                <X />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Button
        type="button"
        variant={files.length > 0 ? "outline" : "secondary"}
        className="justify-center"
        disabled={disabled || opening}
        onClick={pick}
        data-testid="drive-pick"
      >
        {opening ? <Loader2 className="animate-spin" /> : <Plus />}
        {files.length > 0 ? "Choose more" : "Choose from Google Drive"}
      </Button>

      <p className="text-muted-foreground text-xs">
        PDFs and images, up to {MAX_FILE_MB} MB each. PlusGPT sees only what you
        pick, never the rest of your Drive.
      </p>
    </div>
  )
}

/**
 * Shown in place of the picker when there is nothing to pick from yet.
 *
 * `onLeave` closes whatever is hosting this. Connecting a Drive happens on
 * another page, and a dialog left open over the page it sent you to is a
 * dialog covering the button you were sent there to press.
 */
export function DriveNotConnected({ onLeave }: { onLeave?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-6 text-sm">
      <p className="text-muted-foreground">
        Google Drive is not connected to your account yet.
      </p>
      <Button variant="outline" size="sm" asChild>
        <RouterLink
          to="/data-sources"
          search={{ connected: undefined, reason: undefined }}
          onClick={() => onLeave?.()}
          data-testid="drive-connect"
        >
          Connect Google Drive
          <ExternalLink />
        </RouterLink>
      </Button>
    </div>
  )
}
