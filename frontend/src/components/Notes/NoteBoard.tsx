import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { NotebookPen } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { NoteSummaryPublic } from "@/client"
import { EmptyState } from "@/components/Layout/EmptyState"
import { NoteCard, type NoteCardActions } from "@/components/Notes/NoteCard"
import { NoteReminderDialog } from "@/components/Notes/NoteReminderDialog"
import { Skeleton } from "@/components/ui/skeleton"
import {
  type NoteListParams,
  notesQuery,
  pinnedNotesQuery,
  useArchiveUserNote,
  useCloneUserNote,
  useDeleteUserNote,
  usePinUserNote,
} from "@/queries/userNotes"

/**
 * The grid.
 *
 * `minmax(0,1fr)` tracks rather than `auto`: an auto track sizes to the widest
 * indivisible word in it, and a note titled with somebody's 60-character
 * filename would drag the whole page sideways on a phone. The dashboard learnt
 * this the same way.
 */
const GRID =
  "grid gap-3 grid-cols-[repeat(1,minmax(0,1fr))] sm:grid-cols-[repeat(2,minmax(0,1fr))] xl:grid-cols-[repeat(3,minmax(0,1fr))]"

export function NoteBoard({ params }: { params: NoteListParams }) {
  const pinned = useQuery(pinnedNotesQuery(params))
  const { data, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery(notesQuery(params))

  const sentinel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasNextPage) return
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) void fetchNextPage()
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [fetchNextPage, hasNextPage])

  const pin = usePinUserNote()
  const archive = useArchiveUserNote()
  const clone = useCloneUserNote()
  const remove = useDeleteUserNote()

  const [reminding, setReminding] = useState<NoteSummaryPublic | null>(null)

  const actions: NoteCardActions = {
    onRemind: (note) => setReminding(note),
    onPin: (note) => pin.mutate({ id: note.id, pinned: note.pinned }),
    onArchive: (note) =>
      archive.mutate({ id: note.id, archived: note.archived }),
    onClone: (note) => clone.mutate(note.id),
    onDelete: (note) => remove.mutate(note.id),
  }

  const notes = (data?.pages ?? []).flatMap((page) => page.data)
  const showPinned = !params.archived && (pinned.data?.length ?? 0) > 0

  if (isPending) {
    return (
      <div className={GRID} data-testid="notes-board">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-36 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (notes.length === 0 && !showPinned) {
    return <NoteEmpty archived={params.archived === true} />
  }

  return (
    <div className="flex flex-col gap-6" data-testid="notes-board">
      {showPinned && (
        <section className="flex flex-col gap-2" data-testid="notes-pinned">
          <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
            Pinned
          </h2>
          <div className={GRID}>
            {(pinned.data ?? []).map((note: NoteSummaryPublic) => (
              <NoteCard key={note.id} note={note} actions={actions} />
            ))}
          </div>
        </section>
      )}

      {notes.length > 0 && (
        <section className="flex flex-col gap-2">
          {showPinned && (
            <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
              Everything else
            </h2>
          )}
          <div className={GRID}>
            {notes.map((note) => (
              <NoteCard key={note.id} note={note} actions={actions} />
            ))}
          </div>
        </section>
      )}

      {reminding && (
        <NoteReminderDialog
          noteId={reminding.id}
          noteTitle={reminding.title}
          open
          onOpenChange={(next) => !next && setReminding(null)}
        />
      )}

      <div ref={sentinel} className="h-1" />
      {isFetchingNextPage && (
        <div className={GRID}>
          <Skeleton className="h-36 w-full rounded-lg" />
          <Skeleton className="h-36 w-full rounded-lg" />
        </div>
      )}
    </div>
  )
}

function NoteEmpty({ archived }: { archived: boolean }) {
  return (
    <div data-testid="notes-empty">
      <EmptyState
        icon={NotebookPen}
        title={archived ? "Nothing archived" : "Nothing written down yet"}
        description={
          archived
            ? "Archiving keeps a note out of the way without deleting it. Anything you archive stays searchable."
            : "Notes are yours alone. Nobody else can see them, and search and Ask read them alongside your pages."
        }
      />
    </div>
  )
}
