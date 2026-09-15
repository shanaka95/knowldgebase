import { useQuery } from "@tanstack/react-query"
import { formatDistanceToNowStrict } from "date-fns"
import { Check, History, Paperclip } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { documentVersionsQuery } from "@/queries/documentVersions"

interface VersionPickerProps {
  documentId: string
  /** The version the page is on now. */
  current: number
  /** The version being read, if it is not the current one. */
  viewing: number | null
  onSelect: (version: number | null) => void
}

/**
 * Which version of the page is on screen.
 *
 * A version is a change to the words - re-formatting the same sentence is not
 * one - so this reads as a list of things somebody did rather than a list of
 * keystrokes. Where a version was produced by an upload, the files are named
 * against it: that is how the page says which version the original belongs to.
 */
export function VersionPicker({
  documentId,
  current,
  viewing,
  onSelect,
}: VersionPickerProps) {
  const { data, isPending } = useQuery(documentVersionsQuery(documentId))
  const versions = data?.data ?? []
  const reading = viewing ?? current

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={viewing === null ? "ghost" : "outline"}
          size="xs"
          className={cn("gap-1.5", viewing === null && "text-muted-foreground")}
          data-testid="version-picker"
        >
          <History className="size-3.5" />
          Version {reading}
          {viewing !== null && (
            <span className="text-muted-foreground">· older</span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          {versions.length === 1
            ? "This page has one version"
            : `${versions.length} versions, newest first`}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        {isPending && (
          <div className="flex flex-col gap-1 p-1">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        )}

        <div className="max-h-80 overflow-y-auto">
          {versions.map((version) => {
            const files = version.source_filenames ?? []
            return (
              <DropdownMenuItem
                key={version.version}
                className="items-start gap-2 py-2"
                onSelect={() =>
                  onSelect(version.is_current ? null : version.version)
                }
                data-testid="version-option"
              >
                <Check
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    version.version === reading ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="font-medium">
                      Version {version.version}
                    </span>
                    {version.is_current && (
                      <span className="text-xs text-muted-foreground">
                        current
                      </span>
                    )}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {version.created_by_user?.full_name ||
                      version.created_by_user?.email ||
                      "Unknown"}
                    {" · "}
                    {formatDistanceToNowStrict(new Date(version.created_at))}{" "}
                    ago
                    {" · "}
                    {(version.char_count ?? 0).toLocaleString()} characters
                  </span>
                  {files.length > 0 && (
                    <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                      <Paperclip className="size-3 shrink-0" />
                      <span className="truncate">from {files.join(", ")}</span>
                    </span>
                  )}
                </span>
              </DropdownMenuItem>
            )
          })}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
