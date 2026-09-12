import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useState } from "react"

import { attachmentBlobQuery, fetchAttachmentBlob } from "@/queries/attachments"

/**
 * Object URL for an authenticated attachment. The URL is revoked when the
 * component unmounts or the id changes.
 */
export function useAttachmentBlob(attachmentId: string | null | undefined) {
  const query = useQuery({
    ...attachmentBlobQuery(attachmentId ?? ""),
    enabled: Boolean(attachmentId),
  })
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!query.data) {
      setObjectUrl(null)
      return
    }
    const url = URL.createObjectURL(query.data)
    setObjectUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [query.data])

  return { ...query, objectUrl }
}

/** Stable fetcher to hand to the editor's AuthImage node view. */
export function useAttachmentBlobFetcher() {
  const queryClient = useQueryClient()
  return useCallback(
    (attachmentId: string) => fetchAttachmentBlob(queryClient, attachmentId),
    [queryClient],
  )
}
