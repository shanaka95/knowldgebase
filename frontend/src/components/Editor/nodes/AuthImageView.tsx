import { NodeViewWrapper, type ReactNodeViewProps } from "@tiptap/react"
import { ImageOff, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type { AuthImageOptions } from "./AuthImage"

/** Module-level cache of object URLs per attachment id (shared by all editors). */
const blobUrlCache = new Map<string, string>()
const inflight = new Map<string, Promise<string>>()

async function resolveAttachmentUrl(
  id: string,
  fetchBlob: (id: string) => Promise<Blob>,
): Promise<string> {
  const cached = blobUrlCache.get(id)
  if (cached) return cached
  const pending = inflight.get(id)
  if (pending) return pending
  const promise = fetchBlob(id)
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      blobUrlCache.set(id, url)
      return url
    })
    .finally(() => inflight.delete(id))
  inflight.set(id, promise)
  return promise
}

export function invalidateAttachmentBlob(id: string) {
  const url = blobUrlCache.get(id)
  if (url) URL.revokeObjectURL(url)
  blobUrlCache.delete(id)
}

type Status = "idle" | "loading" | "ready" | "error"

export function AuthImageView({
  node,
  selected,
  extension,
  updateAttributes,
  editor,
}: ReactNodeViewProps) {
  const attachmentId = node.attrs["data-attachment-id"] as string | null
  const src = node.attrs.src as string | null
  const alt = (node.attrs.alt as string | null) ?? ""
  const title = node.attrs.title as string | null
  const width = node.attrs.width as string | number | null
  const uploading = Boolean(node.attrs.uploading)
  const fetchBlob = (extension.options as AuthImageOptions).fetchAttachmentBlob

  const needsAuthFetch =
    Boolean(attachmentId) &&
    Boolean(fetchBlob) &&
    !uploading &&
    !(src?.startsWith("blob:") || src?.startsWith("data:"))

  const [status, setStatus] = useState<Status>(
    needsAuthFetch ? "loading" : "ready",
  )
  const [resolvedSrc, setResolvedSrc] = useState<string | null>(
    needsAuthFetch ? null : src,
  )
  const [_attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!needsAuthFetch) {
      setResolvedSrc(src)
      setStatus("ready")
      return
    }
    setStatus("loading")
    resolveAttachmentUrl(
      attachmentId as string,
      fetchBlob as NonNullable<typeof fetchBlob>,
    )
      .then((url) => {
        if (cancelled) return
        setResolvedSrc(url)
        setStatus("ready")
      })
      .catch(() => {
        if (cancelled) return
        setStatus("error")
      })
    return () => {
      cancelled = true
    }
  }, [attachmentId, src, needsAuthFetch, fetchBlob])

  const editable = editor.isEditable

  return (
    <NodeViewWrapper
      className={cn(
        "kb-image relative my-5 flex justify-center",
        selected && editable && "kb-node-selected",
      )}
      data-drag-handle
    >
      {status === "loading" && (
        <div className="relative w-full max-w-xl">
          <Skeleton className="aspect-video w-full rounded-md" />
          <Loader2 className="absolute left-1/2 top-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-muted-foreground" />
        </div>
      )}
      {status === "error" && (
        <div className="flex w-full max-w-xl flex-col items-center gap-2 rounded-md border border-dashed bg-muted/40 p-6 text-center text-sm text-muted-foreground">
          <ImageOff className="size-5" />
          <span>Couldn't load this image.</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (attachmentId) invalidateAttachmentBlob(attachmentId)
              setAttempt((a) => a + 1)
            }}
          >
            Retry
          </Button>
        </div>
      )}
      {status === "ready" && resolvedSrc && (
        <span className="relative inline-block max-w-full">
          <img
            src={resolvedSrc}
            alt={alt}
            title={title ?? undefined}
            width={width ?? undefined}
            className={cn(
              "m-0 max-w-full rounded-md",
              uploading && "opacity-60",
            )}
            draggable={false}
            onDoubleClick={() => {
              if (!editable) return
              const next = window.prompt("Alt text", alt)
              if (next !== null) updateAttributes({ alt: next })
            }}
          />
          {uploading && (
            <span className="absolute inset-x-0 bottom-2 mx-auto flex w-fit items-center gap-1.5 rounded-full bg-background/90 px-2.5 py-1 text-xs text-muted-foreground shadow">
              <Loader2 className="size-3 animate-spin" />
              Uploading…
            </span>
          )}
        </span>
      )}
    </NodeViewWrapper>
  )
}

export default AuthImageView
