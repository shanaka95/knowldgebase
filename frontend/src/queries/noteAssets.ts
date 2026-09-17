import {
  type QueryClient,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"

import { type NoteAssetPublic, UserNotesService } from "@/client"
import { userNoteKeys } from "@/queries/userNotes"

export const noteAssetKeys = {
  list: (noteId: string) => [...userNoteKeys.detail(noteId), "assets"] as const,
  blob: (assetId: string) => ["user-notes", "asset-blob", assetId] as const,
}

export function noteAssetsQuery(noteId: string) {
  return queryOptions({
    queryKey: noteAssetKeys.list(noteId),
    queryFn: async (): Promise<NoteAssetPublic[]> =>
      (
        await UserNotesService.notesReadNoteAssets({
          path: { note_id: noteId },
        })
      ).data?.data ?? [],
  })
}

/**
 * A note's file, fetched with the Authorization header.
 *
 * A private file cannot be a plain `<img src>`: the browser sends no token on
 * an image request, so the route would answer 401 and the card would show a
 * broken picture. The same reason `AuthImage` exists for attachments.
 */
export function noteAssetBlobQuery(noteId: string, assetId: string) {
  return queryOptions({
    queryKey: noteAssetKeys.blob(assetId),
    queryFn: async (): Promise<Blob> => {
      const response = await UserNotesService.notesDownloadNoteAsset({
        path: { note_id: noteId, asset_id: assetId },
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

export function fetchNoteAssetBlob(
  queryClient: QueryClient,
  noteId: string,
  assetId: string,
): Promise<Blob> {
  return queryClient.fetchQuery(noteAssetBlobQuery(noteId, assetId))
}

export function useUploadNoteAsset(noteId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (image: Blob) =>
      (
        await UserNotesService.notesUploadNoteAsset({
          path: { note_id: noteId },
          body: {
            file: new File([image], "drawing.png", { type: "image/png" }),
          },
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: noteAssetKeys.list(noteId),
      })
      // The picture is part of the note's content, so the board's copy of it
      // is stale too - the card shows this drawing.
      void queryClient.invalidateQueries({ queryKey: userNoteKeys.all })
    },
  })
}
