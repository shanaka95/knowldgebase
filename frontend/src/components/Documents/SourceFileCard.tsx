import { Eye, FileText, ImageIcon, Paperclip } from "lucide-react"
import { useState } from "react"

import type { AttachmentPublic } from "@/client"
import { formatBytes, isPdf } from "@/components/Imports/fileHelpers"
import { Button } from "@/components/ui/button"
import { SourceFileDialog } from "./SourceFileDialog"

/**
 * Compact affordance in the document header: the page was imported from this
 * file, and it can be opened at any time.
 */
export function SourceFileChip({
  attachment,
}: {
  attachment: AttachmentPublic
}) {
  const [open, setOpen] = useState(false)
  const pdf = isPdf({
    type: attachment.content_type,
    name: attachment.filename,
  })

  return (
    <>
      <Button
        variant="outline"
        size="xs"
        className="max-w-[16rem] gap-1.5 rounded-full text-muted-foreground"
        onClick={() => setOpen(true)}
        title={`View ${attachment.filename}`}
        data-testid="source-file-chip"
      >
        {pdf ? (
          <FileText className="size-3.5 shrink-0" />
        ) : (
          <ImageIcon className="size-3.5 shrink-0" />
        )}
        <span className="truncate">{attachment.filename}</span>
      </Button>
      <SourceFileDialog
        attachment={attachment}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  )
}

/** Fuller card for the side rail. */
export function SourceFileCard({
  attachment,
}: {
  attachment: AttachmentPublic
}) {
  const [open, setOpen] = useState(false)
  const pdf = isPdf({
    type: attachment.content_type,
    name: attachment.filename,
  })

  return (
    <div className="rounded-lg border p-3" data-testid="source-file-card">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">
        <Paperclip className="size-3.5" />
        Source file
      </p>
      <div className="mt-2 flex items-start gap-2">
        <span className="flex size-8 shrink-0 items-center justify-center rounded bg-muted text-muted-foreground">
          {pdf ? (
            <FileText className="size-4" />
          ) : (
            <ImageIcon className="size-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{attachment.filename}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(attachment.size)}
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="mt-3 w-full"
        onClick={() => setOpen(true)}
        data-testid="source-file-view"
      >
        <Eye className="size-4" />
        View original
      </Button>
      <SourceFileDialog
        attachment={attachment}
        open={open}
        onOpenChange={setOpen}
      />
    </div>
  )
}
