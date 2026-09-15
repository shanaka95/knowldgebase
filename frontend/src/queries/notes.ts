import {
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"

import { type DocumentNotesPublic, NotesService } from "@/client"
import { queryKeys } from "@/lib/queryKeys"

/** The notes on one page, oldest first — the order they were written in. */
export function documentNotesQuery(documentId: string) {
  return queryOptions({
    queryKey: queryKeys.notes.list(documentId),
    queryFn: async (): Promise<DocumentNotesPublic> =>
      (await NotesService.readNotes({ path: { document_id: documentId } }))
        .data,
  })
}

/**
 * Writing a note re-indexes the page, so the document itself is invalidated
 * alongside the list: its note count and its "needs indexing" state both move.
 */
function useNoteMutation<TVariables>(
  documentId: string,
  run: (variables: TVariables) => Promise<unknown>,
  { success, failure }: { success: string; failure: string },
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      toast.success(success)
      queryClient.invalidateQueries({
        queryKey: queryKeys.notes.list(documentId),
      })
      queryClient.invalidateQueries({
        queryKey: queryKeys.documents.detail(documentId),
      })
    },
    onError: (error: Error) => toast.error(error.message || failure),
  })
}

export function useAddNote(documentId: string) {
  return useNoteMutation(
    documentId,
    (body: string) =>
      NotesService.createNote({
        path: { document_id: documentId },
        body: { body },
      }),
    { success: "Note added", failure: "The note could not be added" },
  )
}

export function useEditNote(documentId: string) {
  return useNoteMutation(
    documentId,
    ({ noteId, body }: { noteId: string; body: string }) =>
      NotesService.updateNote({
        path: { document_id: documentId, note_id: noteId },
        body: { body },
      }),
    { success: "Note updated", failure: "The note could not be changed" },
  )
}

export function useDeleteNote(documentId: string) {
  return useNoteMutation(
    documentId,
    (noteId: string) =>
      NotesService.deleteNote({
        path: { document_id: documentId, note_id: noteId },
      }),
    { success: "Note removed", failure: "The note could not be removed" },
  )
}
