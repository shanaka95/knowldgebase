import { useQuery } from "@tanstack/react-query"
import { Check, MessageSquarePlus, Pencil, Trash2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { DocumentNotePublic } from "@/client"
import { Button } from "@/components/ui/button"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { absoluteTime, relativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  documentNotesQuery,
  useAddNote,
  useDeleteNote,
  useEditNote,
} from "@/queries/notes"

/**
 * What people added about this page.
 *
 * Below the content rather than beside it, because a note is read *after* the
 * thing it is about — the rail is for navigating, this is for reading. It is
 * always present, even when empty, since an invisible affordance is one nobody
 * uses: the empty state is the invitation.
 */

const MAX = 4000

export function DocumentNotes({
  documentId,
  className,
}: {
  documentId: string
  className?: string
}) {
  const { data, isPending } = useQuery(documentNotesQuery(documentId))
  const notes = data?.data ?? []

  return (
    <section
      className={cn("flex flex-col gap-3", className)}
      aria-label="Notes"
      data-testid="document-notes"
    >
      <div className="flex items-center gap-2">
        <h2 className="font-medium text-sm">Notes</h2>
        {notes.length > 0 && (
          <span
            className="rounded-full bg-muted px-2 py-0.5 font-mono text-muted-foreground text-xs tabular-nums"
            data-testid="note-count"
          >
            {notes.length}
          </span>
        )}
      </div>

      {isPending ? (
        <Skeleton className="h-20 w-full" />
      ) : (
        <>
          {notes.length > 0 && (
            <ul className="flex flex-col gap-2">
              {notes.map((note) => (
                <NoteRow key={note.id} note={note} documentId={documentId} />
              ))}
            </ul>
          )}
          <Composer documentId={documentId} hasNotes={notes.length > 0} />
        </>
      )}
    </section>
  )
}

function NoteRow({
  note,
  documentId,
}: {
  note: DocumentNotePublic
  documentId: string
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.body)
  const edit = useEditNote(documentId)
  const remove = useDeleteNote(documentId)
  const who = note.author?.full_name || note.author?.email || "Someone"
  const changed = note.updated_at !== note.created_at

  const save = () => {
    const body = draft.trim()
    if (!body || body === note.body) return setEditing(false)
    edit.mutate(
      { noteId: note.id, body },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <li
      className="group rounded-lg border bg-muted/20 px-3 py-2.5"
      data-testid="note"
    >
      <div className="flex items-baseline gap-2">
        <span className="font-medium text-sm">{who}</span>
        <span
          className="text-muted-foreground text-xs"
          title={absoluteTime(note.created_at)}
        >
          {relativeTime(note.created_at)}
          {changed && " · edited"}
        </span>
        <span className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          {note.can_edit && !editing && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Edit note"
              data-testid="edit-note"
              onClick={() => {
                setDraft(note.body)
                setEditing(true)
              }}
            >
              <Pencil />
            </Button>
          )}
          {note.can_delete && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label="Remove note"
              data-testid="delete-note"
              disabled={remove.isPending}
              onClick={() => remove.mutate(note.id)}
            >
              <Trash2 />
            </Button>
          )}
        </span>
      </div>

      {editing ? (
        <div className="mt-2 flex flex-col gap-2">
          <Textarea
            value={draft}
            maxLength={MAX}
            rows={3}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditing(false)
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) save()
            }}
            data-testid="note-edit-input"
          />
          <div className="flex items-center gap-2">
            <LoadingButton
              size="sm"
              loading={edit.isPending}
              onClick={save}
              data-testid="save-note"
            >
              <Check />
              Save
            </LoadingButton>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={edit.isPending}
            >
              <X />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">
          {note.body}
        </p>
      )}
    </li>
  )
}

function Composer({
  documentId,
  hasNotes,
}: {
  documentId: string
  hasNotes: boolean
}) {
  const [open, setOpen] = useState(false)
  const [body, setBody] = useState("")
  const add = useAddNote(documentId)
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (open) ref.current?.focus()
  }, [open])

  const submit = () => {
    const text = body.trim()
    if (!text) return
    add.mutate(text, {
      onSuccess: () => {
        setBody("")
        setOpen(false)
      },
    })
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-lg border border-dashed px-3 py-2.5 text-left text-muted-foreground text-sm transition hover:border-border hover:text-foreground"
        data-testid="add-note"
      >
        <MessageSquarePlus className="size-4 shrink-0" />
        {hasNotes
          ? "Add a note"
          : "Anything you want to add to this document? Put it here."}
      </button>
    )
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <Textarea
        ref={ref}
        rows={3}
        maxLength={MAX}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false)
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit()
        }}
        placeholder="Context the document itself does not give — why it was kept, what it replaces, what to watch out for."
        data-testid="note-input"
      />
      <div className="flex items-center gap-2">
        <LoadingButton
          size="sm"
          loading={add.isPending}
          disabled={!body.trim()}
          onClick={submit}
          data-testid="save-new-note"
        >
          Add note
        </LoadingButton>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setOpen(false)}
          disabled={add.isPending}
        >
          Cancel
        </Button>
        <span className="ml-auto text-muted-foreground text-xs">
          Notes are searchable with the page.
        </span>
      </div>
    </div>
  )
}
