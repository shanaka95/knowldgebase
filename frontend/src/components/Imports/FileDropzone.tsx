import { FileText, ImageIcon, Upload, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  ACCEPTED_IMPORT_TYPES,
  formatBytes,
  isPdf,
  rejectionReason,
} from "./fileHelpers"

interface Props {
  file: File | null
  onFile: (file: File | null) => void
  onReject: (message: string) => void
  disabled?: boolean
}

/** Preview thumbnail for images; revoked when the file changes. */
function useImagePreview(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!file || isPdf(file)) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(file)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [file])
  return url
}

export function FileDropzone({ file, onFile, onReject, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const preview = useImagePreview(file)

  const accept = (candidate: File | undefined) => {
    if (!candidate) return
    const reason = rejectionReason(candidate)
    if (reason) {
      onReject(reason)
      return
    }
    onFile(candidate)
  }

  if (file) {
    return (
      <div
        className="flex items-center gap-3 rounded-lg border bg-muted/30 p-3"
        data-testid="import-file-preview"
      >
        {preview ? (
          <img
            src={preview}
            alt=""
            className="size-12 shrink-0 rounded object-cover"
          />
        ) : (
          <span className="flex size-12 shrink-0 items-center justify-center rounded bg-background text-muted-foreground">
            {isPdf(file) ? (
              <FileText className="size-5" />
            ) : (
              <ImageIcon className="size-5" />
            )}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <p className="text-xs text-muted-foreground">
            {formatBytes(file.size)}
            {isPdf(file) ? " · PDF" : " · image"}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Choose a different file"
          disabled={disabled}
          onClick={() => onFile(null)}
          data-testid="import-clear-file"
        >
          <X className="size-4" />
        </Button>
      </div>
    )
  }

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          accept(e.dataTransfer.files?.[0])
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
          "hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          dragging && "border-primary bg-primary/5",
          disabled && "pointer-events-none opacity-60",
        )}
        data-testid="import-dropzone"
      >
        <Upload className="size-6 text-muted-foreground" />
        <span className="text-sm font-medium">
          Drop a PDF or image here, or click to browse
        </span>
        <span className="text-xs text-muted-foreground">
          PDF, PNG, JPEG, WebP, GIF, BMP or TIFF · up to 50 MB
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_IMPORT_TYPES}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          accept(e.target.files?.[0])
          e.target.value = ""
        }}
        data-testid="import-file-input"
      />
    </>
  )
}
