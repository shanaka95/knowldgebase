import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  X,
} from "lucide-react"
import { useEffect, useState } from "react"

import type { AttachmentPublic } from "@/client"
import { isPdf } from "@/components/Imports/fileHelpers"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useAttachmentBlob } from "@/hooks/useAttachmentBlob"

interface Props {
  /** Every original of this page, so the viewer can page through them. */
  attachments: AttachmentPublic[]
  /** Which one to open on. */
  index: number
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * The original file, as big as the screen allows.
 *
 * A scanned page is portrait and text-dense: read at a third of a desktop
 * window it is a thumbnail, not a document. So the viewer takes the whole
 * viewport bar a margin, and on a phone it takes all of it - there is no room
 * there for a frame around the thing you are trying to read.
 *
 * When a page was built from several files this pages between them, rather
 * than making somebody close the viewer and open the next chip.
 */
export function SourceFileDialog({
  attachments,
  index,
  open,
  onOpenChange,
}: Props) {
  const [current, setCurrent] = useState(index)

  // Opening from a different chip should land on that file.
  useEffect(() => {
    if (open) setCurrent(index)
  }, [open, index])

  const attachment = attachments[current] ?? attachments[0]
  const { objectUrl, isPending, isError, error } = useAttachmentBlob(
    open && attachment ? attachment.id : null,
  )
  const many = attachments.length > 1

  useEffect(() => {
    if (!open || !many) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") {
        setCurrent((i) => Math.min(i + 1, attachments.length - 1))
      }
      if (e.key === "ArrowLeft") setCurrent((i) => Math.max(i - 1, 0))
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, many, attachments.length])

  if (!attachment) return null
  const pdf = isPdf({
    type: attachment.content_type,
    name: attachment.filename,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/*
        Sized off the viewport rather than a breakpoint: `max-w-4xl` made a
        scan unreadable on a large screen and a modal-within-a-modal on a
        small one. `100dvh` rather than `vh` so a phone's address bar does not
        hide the controls.
      */}
      <DialogContent
        showCloseButton={false}
        className="flex h-[100dvh] w-screen max-w-none flex-col gap-0 rounded-none border-0 p-0 sm:h-[92dvh] sm:w-[96vw] sm:max-w-[1400px] sm:rounded-lg sm:border"
        data-testid="source-file-dialog"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2 sm:px-4">
          <div className="min-w-0 flex-1">
            <DialogTitle className="truncate text-sm font-medium">
              {attachment.filename}
            </DialogTitle>
            <p className="truncate text-xs text-muted-foreground">
              {many
                ? `${current + 1} of ${attachments.length} files this page was made from`
                : "The file this page was imported from"}
            </p>
          </div>

          {many && (
            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Previous file"
                disabled={current === 0}
                onClick={() => setCurrent((i) => Math.max(i - 1, 0))}
                data-testid="source-file-prev"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Next file"
                disabled={current === attachments.length - 1}
                onClick={() =>
                  setCurrent((i) => Math.min(i + 1, attachments.length - 1))
                }
                data-testid="source-file-next"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}

          <Button asChild variant="outline" size="sm" className="shrink-0">
            <a
              href={objectUrl ?? "#"}
              download={attachment.filename}
              data-testid="source-file-download"
            >
              <Download className="size-4" />
              <span className="hidden sm:inline">Download</span>
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="shrink-0"
            aria-label="Close"
            onClick={() => onOpenChange(false)}
          >
            <X className="size-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden bg-muted/30">
          {isPending && !objectUrl && (
            <Skeleton className="size-full" data-testid="source-file-loading" />
          )}
          {isError && (
            <div className="p-4">
              <Alert variant="destructive">
                <AlertCircle />
                <AlertDescription>
                  {error instanceof Error
                    ? error.message
                    : "The file could not be loaded."}
                </AlertDescription>
              </Alert>
            </div>
          )}
          {objectUrl &&
            (pdf ? (
              // <object> falls back to its children when the browser has no
              // inline PDF viewer, instead of showing a blank frame
              <object
                key={attachment.id}
                data={objectUrl}
                type="application/pdf"
                title={attachment.filename}
                className="size-full"
                data-testid="source-file-pdf"
              >
                <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center">
                  <p className="text-sm text-muted-foreground">
                    This browser cannot show PDFs inline.
                  </p>
                  <Button asChild size="sm">
                    <a href={objectUrl} download={attachment.filename}>
                      <Download className="size-4" />
                      Download {attachment.filename}
                    </a>
                  </Button>
                </div>
              </object>
            ) : (
              // Scrollable rather than letterboxed: a tall scan on a phone is
              // meant to be read by scrolling down it, not shrunk to fit.
              <div className="size-full overflow-auto p-2 sm:p-4">
                <img
                  src={objectUrl}
                  alt={attachment.filename}
                  className="mx-auto max-w-full sm:min-h-full sm:object-contain"
                  data-testid="source-file-image"
                />
              </div>
            ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
