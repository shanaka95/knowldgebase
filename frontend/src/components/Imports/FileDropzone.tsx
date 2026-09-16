import { Camera, FileText, ImageIcon, Upload, X } from "lucide-react"
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
  files: File[]
  onFiles: (files: File[]) => void
  onReject: (message: string) => void
  disabled?: boolean
  max?: number
}

/**
 * Whether to offer the camera.
 *
 * Asked of the pointer rather than the hardware: a laptop has a webcam and
 * nobody photographs a letter with it, while a phone or tablet is the device
 * people actually hold over a piece of paper. A coarse pointer is the closest
 * honest proxy for "this is held, not typed at".
 */
function useCameraAvailable(): boolean {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const touch = window.matchMedia("(pointer: coarse)").matches
    const hasCamera = Boolean(navigator.mediaDevices?.getUserMedia)
    setAvailable(touch && hasCamera)
  }, [])
  return available
}

/**
 * A photograph arrives named whatever the camera felt like - often "image.jpg"
 * for every shot. Naming them in order keeps the list readable and stops two
 * captures looking like the same file to the duplicate check.
 */
function namedCapture(file: File, position: number): File {
  const stamp = new Date().toISOString().slice(0, 10)
  const extension = file.name.includes(".") ? file.name.split(".").pop() : "jpg"
  return new File([file], `Photo ${position} (${stamp}).${extension}`, {
    type: file.type,
    lastModified: file.lastModified,
  })
}

/** Preview thumbnail for images; revoked when the file changes. */
function useImagePreview(file: File): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (isPdf(file)) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(file)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [file])
  return url
}

function FileRow({
  file,
  index,
  onRemove,
  disabled,
}: {
  file: File
  index: number
  onRemove: () => void
  disabled?: boolean
}) {
  const preview = useImagePreview(file)
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
        <p className="truncate font-medium text-sm" title={file.name}>
          {file.name}
        </p>
        <p className="text-muted-foreground text-xs">
          {formatBytes(file.size)}
          {isPdf(file) ? " · PDF" : " · image"}
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        aria-label={`Remove ${file.name}`}
        disabled={disabled}
        onClick={onRemove}
        data-testid={index === 0 ? "import-clear-file" : "import-remove-file"}
      >
        <X className="size-4" />
      </Button>
    </div>
  )
}

export function FileDropzone({
  files,
  onFiles,
  onReject,
  disabled,
  max = 20,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const cameraAvailable = useCameraAvailable()

  /**
   * Add what is acceptable and explain what is not, rather than discarding the
   * whole selection because one file in it was the wrong type. Someone who
   * selected twelve scans and one stray text file should end up with twelve
   * scans queued and a sentence about the thirteenth.
   */
  const accept = (candidates: FileList | File[] | null | undefined) => {
    const incoming = Array.from(candidates ?? [])
    if (incoming.length === 0) return

    const accepted: File[] = []
    const refused: string[] = []
    for (const candidate of incoming) {
      const reason = rejectionReason(candidate)
      if (reason) {
        refused.push(reason)
        continue
      }
      // The same file chosen twice is almost always a slip, not an intention to
      // import it twice.
      const duplicate = files.some(
        (f) =>
          f.name === candidate.name &&
          f.size === candidate.size &&
          f.lastModified === candidate.lastModified,
      )
      if (!duplicate) accepted.push(candidate)
    }

    const room = max - files.length
    const kept = accepted.slice(0, Math.max(room, 0))
    if (accepted.length > kept.length) {
      refused.push(`Up to ${max} files at a time.`)
    }
    if (kept.length > 0) onFiles([...files, ...kept])
    if (refused.length > 0) onReject(refused[0])
  }

  const remove = (index: number) => onFiles(files.filter((_, i) => i !== index))

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {files.length > 0 && (
        <div className="flex min-w-0 flex-col gap-2">
          {files.map((file, index) => (
            <FileRow
              key={`${file.name}-${file.size}-${file.lastModified}`}
              file={file}
              index={index}
              onRemove={() => remove(index)}
              disabled={disabled}
            />
          ))}
        </div>
      )}

      {files.length < max && cameraAvailable && (
        // First, because on a phone the camera is usually why someone opened
        // this at all - the document is on the table in front of them.
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => cameraRef.current?.click()}
          className="w-full"
          data-testid="capture-photo"
        >
          <Camera />
          {files.length > 0 ? "Take another photo" : "Take a photo"}
        </Button>
      )}

      {files.length < max && (
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
            accept(e.dataTransfer.files)
          }}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 text-center transition-colors",
            "hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            // Once files are listed above, the target is a slim "add more" strip
            // rather than the large empty-state panel.
            files.length > 0 ? "py-4" : "py-8",
            dragging && "border-primary bg-primary/5",
            disabled && "pointer-events-none opacity-60",
          )}
          data-testid="import-dropzone"
        >
          <Upload className="size-6 text-muted-foreground" />
          <span className="font-medium text-sm">
            {files.length > 0
              ? "Add more files"
              : cameraAvailable
                ? "Or choose a file"
                : "Drop PDFs or images here, or click to browse"}
          </span>
          {files.length === 0 && (
            <span className="text-muted-foreground text-xs">
              PDF, PNG, JPEG, WebP, GIF, BMP or TIFF · up to 50 MB each
            </span>
          )}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_IMPORT_TYPES}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          accept(e.target.files)
          e.target.value = ""
        }}
        data-testid="import-file-input"
      />

      {/*
        A separate input because `capture` changes what the control *is*: on a
        phone it opens the camera directly rather than the file picker. One shot
        per press, which is why the button says "take another" - each capture
        appends, so a three-page letter is three presses.
      */}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const shot = e.target.files?.[0]
          if (shot) accept([namedCapture(shot, files.length + 1)])
          e.target.value = ""
        }}
        data-testid="capture-camera-input"
      />
    </div>
  )
}
