import { type QueryClient, queryOptions } from "@tanstack/react-query"

import { AttachmentsService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** Downloads an attachment with the Authorization header; cached forever per id. */
export function attachmentBlobQuery(attachmentId: string) {
  return queryOptions({
    queryKey: queryKeys.attachmentBlob(attachmentId),
    queryFn: async (): Promise<Blob> => {
      const response = await AttachmentsService.downloadAttachment({
        path: { attachment_id: attachmentId },
        responseType: "blob",
      })
      const data = response.data as unknown
      if (data instanceof Blob) return data
      return new Blob([data as BlobPart])
    },
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 30 * 60 * 1_000,
  })
}

export function fetchAttachmentBlob(
  queryClient: QueryClient,
  attachmentId: string,
): Promise<Blob> {
  return queryClient.fetchQuery(attachmentBlobQuery(attachmentId))
}
