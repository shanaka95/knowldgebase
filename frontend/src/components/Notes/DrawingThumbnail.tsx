import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { noteAssetBlobQuery } from "@/queries/noteAssets"

/**
 * The picture of a drawing note, on a card.
 *
 * A private file cannot be a plain `<img src>`: the browser sends no
 * Authorization header on an image request, so the route would answer 404 and
 * every card would show a broken picture. The bytes are fetched with the rest
 * of the client's credentials and turned into an object URL, exactly as
 * `AuthImage` does for a page's attachments.
 *
 * The blob is cached per asset id and never goes stale, because a redraw
 * uploads a new file with a new id rather than replacing one.
 */
export function DrawingThumbnail({
  noteId,
  assetId,
}: {
  noteId: string
  assetId: string
}) {
  const { data, isPending, isError } = useQuery(
    noteAssetBlobQuery(noteId, assetId),
  )
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    const objectUrl = URL.createObjectURL(data)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [data])

  if (isError) return null
  if (isPending || !url) {
    return <Skeleton className="aspect-[8/5] w-full rounded-md" />
  }
  return (
    <img
      src={url}
      alt=""
      className="aspect-[8/5] w-full rounded-md border bg-white object-contain"
      data-testid="notes-card-drawing"
    />
  )
}
