import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"

import {
  type NoteCreate,
  type NoteKind,
  type NotePublic,
  type NoteSummaryPublic,
  type NoteTagCreate,
  type NoteTagPublic,
  type NoteUpdate,
  UserNotesService,
} from "@/client"

/**
 * Keys live here rather than in the shared factory because `queryKeys.notes`
 * already belongs to the remarks people leave on a page, and is keyed under
 * `["documents", id, "notes"]`. Two features called notes sharing one cache
 * namespace is a bug waiting for somebody to invalidate the wrong half.
 */
export const userNoteKeys = {
  all: ["user-notes"] as const,
  list: (params: Record<string, unknown>) =>
    ["user-notes", "list", params] as const,
  pinned: (space: string | null) => ["user-notes", "pinned", space] as const,
  detail: (id: string) => ["user-notes", id] as const,
  search: (params: Record<string, unknown>) =>
    ["user-notes", "search", params] as const,
  tags: () => ["user-notes", "tags"] as const,
}

export const NOTES_PAGE_SIZE = 24

export interface NoteListParams {
  namespaceId?: string | null
  kind?: NoteKind | null
  tagId?: string | null
  archived?: boolean
  pinned?: boolean | null
}

function listQuery(params: NoteListParams) {
  return {
    namespace_id: params.namespaceId ?? undefined,
    kind: params.kind ?? undefined,
    tag_id: params.tagId ?? undefined,
    archived: params.archived ?? false,
    pinned: params.pinned ?? undefined,
  }
}

/** The board, a page at a time. */
export function notesQuery(params: NoteListParams) {
  return infiniteQueryOptions({
    queryKey: userNoteKeys.list({ ...listQuery(params), pinned: false }),
    queryFn: async ({ pageParam }) =>
      (
        await UserNotesService.notesReadNotes({
          query: {
            ...listQuery(params),
            pinned: false,
            skip: pageParam,
            limit: NOTES_PAGE_SIZE,
          },
        })
      ).data,
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.data.length, 0)
      return loaded < last.count ? loaded : undefined
    },
    staleTime: 30_000,
  })
}

/**
 * Pinned notes are their own query rather than the front of the infinite list.
 * Splitting a run of pinned rows out of page one breaks the moment somebody
 * pins while page three is loaded, and the optimistic toggle then has to move
 * an item between pages.
 */
export function pinnedNotesQuery(params: NoteListParams) {
  return queryOptions({
    queryKey: userNoteKeys.pinned(params.namespaceId ?? null),
    queryFn: async (): Promise<NoteSummaryPublic[]> =>
      (
        await UserNotesService.notesReadNotes({
          query: {
            namespace_id: params.namespaceId ?? undefined,
            archived: false,
            pinned: true,
            limit: 50,
          },
        })
      ).data.data,
    staleTime: 30_000,
  })
}

export function noteQuery(noteId: string) {
  return queryOptions({
    queryKey: userNoteKeys.detail(noteId),
    queryFn: async (): Promise<NotePublic> =>
      (await UserNotesService.notesReadNote({ path: { note_id: noteId } }))
        .data,
  })
}

export interface NoteSearchParams {
  q: string
  namespaceId?: string | null
  kind?: NoteKind | null
  includeArchived?: boolean
}

export function noteSearchQuery(params: NoteSearchParams) {
  const q = params.q.trim()
  return queryOptions({
    queryKey: userNoteKeys.search({
      q,
      namespace_id: params.namespaceId ?? null,
      kind: params.kind ?? null,
      archived: params.includeArchived ?? true,
    }),
    queryFn: async (): Promise<NoteSummaryPublic[]> =>
      (
        await UserNotesService.notesSearchNotes({
          query: {
            q,
            namespace_id: params.namespaceId ?? undefined,
            kind: params.kind ?? undefined,
            include_archived: params.includeArchived ?? true,
          },
        })
      ).data.data,
    enabled: q.length > 0,
    placeholderData: (prev) => prev,
    staleTime: 30_000,
  })
}

export function noteTagsQuery() {
  return queryOptions({
    queryKey: userNoteKeys.tags(),
    queryFn: async (): Promise<NoteTagPublic[]> =>
      (await UserNotesService.notesReadTags()).data.data,
    staleTime: 60_000,
  })
}

// --- mutations --------------------------------------------------------------

/**
 * Everything that changes a note invalidates the whole namespace.
 *
 * Deliberately blunt: a note appears in a list, a pinned list, an archive view
 * and a detail query at once, and working out which of those a pin affects is
 * how one of them ends up stale. These are small payloads.
 */
function useNoteMutation<TVariables, TData>(
  run: (variables: TVariables) => Promise<TData>,
  messages: { success?: string; failure: string } = {
    failure: "That did not work",
  },
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      if (messages.success) toast.success(messages.success)
      void queryClient.invalidateQueries({ queryKey: userNoteKeys.all })
    },
    onError: (error: Error) => toast.error(error.message || messages.failure),
  })
}

export function useCreateUserNote() {
  return useNoteMutation(
    async (body: NoteCreate) =>
      (await UserNotesService.notesCreateNote({ body })).data,
    { failure: "The note could not be saved" },
  )
}

export function useSaveUserNote(noteId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: NoteUpdate) =>
      (
        await UserNotesService.notesUpdateNote({
          path: { note_id: noteId },
          body,
        })
      ).data,
    onSuccess: (note) => {
      queryClient.setQueryData(userNoteKeys.detail(noteId), note)
      void queryClient.invalidateQueries({ queryKey: userNoteKeys.list({}) })
    },
  })
}

export function usePinUserNote() {
  return useNoteMutation(
    async ({ id, pinned }: { id: string; pinned: boolean }) =>
      pinned
        ? (await UserNotesService.notesUnpinNote({ path: { note_id: id } }))
            .data
        : (await UserNotesService.notesPinNote({ path: { note_id: id } })).data,
    { failure: "The pin could not be changed" },
  )
}

export function useArchiveUserNote() {
  return useNoteMutation(
    async ({ id, archived }: { id: string; archived: boolean }) =>
      archived
        ? (await UserNotesService.notesUnarchiveNote({ path: { note_id: id } }))
            .data
        : (await UserNotesService.notesArchiveNote({ path: { note_id: id } }))
            .data,
    { failure: "The note could not be archived" },
  )
}

export function useCloneUserNote() {
  return useNoteMutation(
    async (id: string) =>
      (await UserNotesService.notesCloneNote({ path: { note_id: id } })).data,
    { success: "Copied", failure: "The note could not be copied" },
  )
}

export function useMoveUserNote() {
  return useNoteMutation(
    async ({ id, namespaceId }: { id: string; namespaceId: string | null }) =>
      (
        await UserNotesService.notesMoveNote({
          path: { note_id: id },
          body: { namespace_id: namespaceId },
        })
      ).data,
    { success: "Moved", failure: "The note could not be moved" },
  )
}

export function useDeleteUserNote() {
  return useNoteMutation(
    async (id: string) =>
      (await UserNotesService.notesDeleteNote({ path: { note_id: id } })).data,
    { success: "Deleted", failure: "The note could not be deleted" },
  )
}

export function useCreateNoteTag() {
  return useNoteMutation(
    async (body: NoteTagCreate) =>
      (await UserNotesService.notesCreateTag({ body })).data,
    { failure: "The tag could not be made" },
  )
}

export function useDeleteNoteTag() {
  return useNoteMutation(
    async (id: string) =>
      (await UserNotesService.notesDeleteTag({ path: { tag_id: id } })).data,
    { success: "Tag removed", failure: "The tag could not be removed" },
  )
}
