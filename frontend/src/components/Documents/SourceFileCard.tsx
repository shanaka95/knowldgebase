import { Eye, FileText, ImageIcon, Paperclip } from "lucide-react"
import { useState } from "react"

import type { AttachmentPublic } from "@/client"
import { formatBytes, isPdf } from "@/components/Imports/fileHelpers"
import { Button } from "@/components/ui/button"
import { SourceFileDialog } from "./SourceFileDialog"

function FileIcon({
  attachment,
  className,
}: {
  attachment: AttachmentPublic
  className?: string
}) {
  const pdf = isPdf({
    type: attachment.content_type,
    name: attachment.filename,
  })
  return pdf ? (
    <FileText className={className} />
  ) : (
    <ImageIcon className={className} />
  )
}

/**
 * The originals in the document header: one chip per file.
 *
 * A page combined from eight scans used to offer the first one and keep the
 * other seven to itself, even though all eight were stored. Each chip opens
 * the viewer on its own file, and the viewer pages between them from there.
 */
export function SourceFileChips({
  attachments,
}: {
  attachments: AttachmentPublic[]
}) {
  const [openAt, setOpenAt] = useState<number | null>(null)
  if (attachments.length === 0) return null

  return (
    <>
      <div className="flex flex-wrap items-center gap-1.5">
        {attachments.map((attachment, index) => (
          <Button
            key={attachment.id}
            variant="outline"
            size="xs"
            className="max-w-[16rem] gap-1.5 rounded-full text-muted-foreground"
            onClick={() => setOpenAt(index)}
            title={`View ${attachment.filename}`}
            data-testid="source-file-chip"
          >
            <FileIcon attachment={attachment} className="size-3.5 shrink-0" />
            <span className="truncate">{attachment.filename}</span>
          </Button>
        ))}
      </div>
      <SourceFileDialog
        attachments={attachments}
        index={openAt ?? 0}
        open={openAt !== null}
        onOpenChange={(open) => !open && setOpenAt(null)}
      />
    </>
  )
}

/** Fuller card for the side rail, listing every file the page came from. */
export function SourceFileCard({
  attachments,
  version,
}: {
  attachments: AttachmentPublic[]
  /** The page version these files produced, so the card can say so. */
  version?: number | null
}) {
  const [openAt, setOpenAt] = useState<number | null>(null)
  if (attachments.length === 0) return null

  const many = attachments.length > 1
  const belongsTo = version ?? attachments[0].source_version ?? null

  return (
    <div className="rounded-lg border p-3" data-testid="source-file-card">
      <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Paperclip className="size-3.5" />
        {many ? `${attachments.length} original files` : "Source file"}
      </p>
      {belongsTo !== null && (
        <p className="mt-1 text-xs text-muted-foreground">
          This page was created from {many ? "these" : "this"} at version{" "}
          {belongsTo}.
        </p>
      )}

      <ul className="mt-2 flex flex-col gap-2">
        {attachments.map((attachment, index) => (
          <li key={attachment.id} className="flex items-start gap-2">
            <span className="flex size-8 shrink-0 items-center justify-center rounded bg-muted text-muted-foreground">
              <FileIcon attachment={attachment} className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {attachment.filename}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatBytes(attachment.size)}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`View ${attachment.filename}`}
              onClick={() => setOpenAt(index)}
              data-testid="source-file-view"
            >
              <Eye className="size-4" />
            </Button>
          </li>
        ))}
      </ul>

      <Button
        variant="outline"
        size="sm"
        className="mt-3 w-full"
        onClick={() => setOpenAt(0)}
        data-testid="source-file-view-all"
      >
        <Eye className="size-4" />
        {many ? "View originals" : "View original"}
      </Button>

      <SourceFileDialog
        attachments={attachments}
        index={openAt ?? 0}
        open={openAt !== null}
        onOpenChange={(open) => !open && setOpenAt(null)}
      />
    </div>
  )
}
