import { useNavigate } from "@tanstack/react-router"
import { ListChecks, NotebookPen, Pencil } from "lucide-react"
import { useState } from "react"

import type { NoteKind } from "@/client"
import { DictateButton } from "@/components/Notes/DictateButton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { Textarea } from "@/components/ui/textarea"
import { useCreateUserNote } from "@/queries/userNotes"

/** A checklist note is a Tiptap document whose body is one task list. */
function seedFor(kind: NoteKind, body: string): string {
  const lines = body
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
  if (kind === "checklist") {
    const items = (lines.length ? lines : [""])
      .map(
        (line) =>
          `<li data-checked="false"><div><p>${escapeHtml(line)}</p></div></li>`,
      )
      .join("")
    return `<ul data-type="taskList">${items}</ul>`
  }
  return lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("") || "<p></p>"
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}

/**
 * Capture, at the top of the board.
 *
 * Collapsed it is one line. Saving keeps you on the board rather than opening
 * the note: a thought you just wrote down should not yank you somewhere else,
 * and the new card is one click away.
 */
export function NoteComposer({
  namespaceId,
  onCreated,
}: {
  namespaceId: string | null
  onCreated?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<NoteKind>("text")
  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const create = useCreateUserNote()
  const navigate = useNavigate()

  // A drawing is the one kind that cannot be started here: there is nothing to
  // type. It is created empty and opened, because the surface needs the room.
  const startDrawing = () =>
    create.mutate(
      {
        namespace_id: namespaceId,
        kind: "drawing",
        title: "",
        content_json: { caption: "", strokes: [] },
      },
      {
        onSuccess: (note) => {
          if (note)
            void navigate({ to: "/notes/$noteId", params: { noteId: note.id } })
        },
      },
    )

  const reset = () => {
    setTitle("")
    setBody("")
    setKind("text")
    setOpen(false)
  }

  const save = () => {
    if (!title.trim() && !body.trim()) {
      reset()
      return
    }
    create.mutate(
      {
        namespace_id: namespaceId,
        kind,
        title: title.trim(),
        content: seedFor(kind, body),
        content_format: "html",
      },
      {
        onSuccess: () => {
          reset()
          onCreated?.()
        },
      },
    )
  }

  if (!open) {
    return (
      <div
        className="flex min-w-0 items-center gap-2 rounded-lg border bg-card p-2"
        data-testid="notes-composer"
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="min-w-0 flex-1 truncate px-2 text-left text-muted-foreground text-sm"
          data-testid="notes-composer-open"
        >
          Take a note…
        </button>
        <DictateButton
          label="Take a note by speaking"
          onText={(text) => {
            setKind("text")
            setBody(text)
            setOpen(true)
          }}
        />
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="New checklist"
          data-testid="notes-new-checklist"
          onClick={() => {
            setKind("checklist")
            setOpen(true)
          }}
        >
          <ListChecks />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="New drawing"
          data-testid="notes-new-drawing"
          onClick={startDrawing}
        >
          <Pencil />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="New note"
          data-testid="notes-new-rich"
          onClick={() => {
            setKind("text")
            setOpen(true)
          }}
        >
          <NotebookPen />
        </Button>
      </div>
    )
  }

  return (
    <div
      className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 shadow-sm"
      data-testid="notes-composer"
    >
      <Input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        aria-label="Title"
        data-testid="notes-composer-title"
      />
      <Textarea
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={
          kind === "checklist" ? "One item per line" : "Write something down"
        }
        aria-label="Note"
        data-testid="notes-composer-input"
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") save()
          if (e.key === "Escape") reset()
        }}
      />
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button
            variant={kind === "text" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setKind("text")}
          >
            <NotebookPen />
            Note
          </Button>
          <Button
            variant={kind === "checklist" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setKind("checklist")}
          >
            <ListChecks />
            Checklist
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <DictateButton
            onText={(text) =>
              setBody((current) =>
                current.trim() ? `${current.trimEnd()}\n${text}` : text,
              )
            }
          />
          <Button variant="ghost" size="sm" onClick={reset}>
            Cancel
          </Button>
          <LoadingButton
            size="sm"
            loading={create.isPending}
            onClick={save}
            data-testid="notes-composer-save"
          >
            Save
          </LoadingButton>
        </div>
      </div>
    </div>
  )
}
