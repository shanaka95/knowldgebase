import { AlertCircle, Download } from "lucide-react"

import type { AttachmentPublic } from "@/client"
import { isPdf } from "@/components/Imports/fileHelpers"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useAttachmentBlob } from "@/hooks/useAttachmentBlob"

interface Props {
  attachment: AttachmentPublic
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Shows the original uploaded file, fetched with the Authorization header. */
export function SourceFileDialog({ attachment, open, onOpenChange }: Props) {
  const { objectUrl, isPending, isError, error } = useAttachmentBlob(
    open ? attachment.id : null,
  )
  const pdf = isPdf({
    type: attachment.content_type,
    name: attachment.filename,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex h-[85vh] max-w-4xl flex-col gap-3 sm:max-w-4xl"
        data-testid="source-file-dialog"
      >
        <DialogHeader className="pr-10">
          <DialogTitle className="truncate">{attachment.filename}</DialogTitle>
          <DialogDescription>
            The file this page was imported from.
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-hidden rounded-md border bg-muted/30">
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
              <div className="flex size-full items-center justify-center overflow-auto p-4">
                <img
                  src={objectUrl}
                  alt={attachment.filename}
                  className="max-h-full max-w-full object-contain"
                  data-testid="source-file-image"
                />
              </div>
            ))}
        </div>

        <div className="flex justify-end">
          <Button asChild variant="outline" size="sm" disabled={!objectUrl}>
            <a
              href={objectUrl ?? "#"}
              download={attachment.filename}
              data-testid="source-file-download"
            >
              <Download className="size-4" />
              Download
            </a>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
