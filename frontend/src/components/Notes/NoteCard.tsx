import { Link } from "@tanstack/react-router"
import {
  Archive,
  ArchiveRestore,
  Bell,
  Copy,
  ListChecks,
  MoreHorizontal,
  NotebookPen,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react"

import type { NoteSummaryPublic } from "@/client"
import { DrawingThumbnail } from "@/components/Notes/DrawingThumbnail"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { relativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const KIND_ICON = {
  text: NotebookPen,
  checklist: ListChecks,
  drawing: Pencil,
} as const

export interface NoteCardActions {
  onRemind: (note: NoteSummaryPublic) => void
  onPin: (note: NoteSummaryPublic) => void
  onArchive: (note: NoteSummaryPublic) => void
  onClone: (note: NoteSummaryPublic) => void
  onDelete: (note: NoteSummaryPublic) => void
}

/**
 * One note on the board.
 *
 * Renders the server's plain-text preview rather than mounting an editor: a
 * board of twenty-four notes would otherwise be twenty-four ProseMirror
 * instances, and it keeps stored HTML out of the card entirely.
 */
export function NoteCard({
  note,
  actions,
}: {
  note: NoteSummaryPublic
  actions: NoteCardActions
}) {
  const Icon = KIND_ICON[note.kind] ?? NotebookPen
  const total = note.checklist_total ?? 0
  const doneCount = note.checklist_done ?? 0

  return (
    <div
      className={cn(
        "group/note relative flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 transition-shadow hover:shadow-sm",
        note.archived && "opacity-70",
      )}
      data-testid="notes-card"
      data-note-id={note.id}
      data-kind={note.kind}
      data-pinned={note.pinned}
    >
      <div className="flex min-w-0 items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <Link
          to="/notes/$noteId"
          params={{ noteId: note.id }}
          className="min-w-0 flex-1 font-medium text-sm hover:underline"
        >
          <span className="line-clamp-2 wrap-anywhere">
            {note.title || "Untitled"}
          </span>
        </Link>
        <NoteMenu note={note} actions={actions} />
      </div>

      {note.drawing_asset_id && (
        <DrawingThumbnail noteId={note.id} assetId={note.drawing_asset_id} />
      )}

      {note.preview && (
        // On a drawing this is what the vision pass saw, which is also what
        // makes the sketch findable. Short, because the picture is above it.
        <p
          className={cn(
            "wrap-anywhere text-muted-foreground text-sm",
            note.drawing_asset_id ? "line-clamp-2" : "line-clamp-5",
          )}
        >
          {note.preview}
        </p>
      )}

      <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-muted-foreground text-xs">
        {note.pinned && (
          <Badge variant="outline" className="shrink-0 gap-1">
            <Pin className="size-3" />
            Pinned
          </Badge>
        )}
        {note.archived && (
          <Badge variant="outline" className="shrink-0">
            Archived
          </Badge>
        )}
        {total > 0 && (
          <Badge variant="outline" className="shrink-0 tabular-nums">
            {doneCount}/{total}
          </Badge>
        )}
        {(note.tags ?? []).map((tag) => (
          <Badge key={tag.id} variant="secondary" className="shrink-0 max-w-32">
            <span className="truncate">{tag.name}</span>
          </Badge>
        ))}
        <span className="shrink-0">{relativeTime(note.updated_at)}</span>
      </div>
    </div>
  )
}

function NoteMenu({
  note,
  actions,
}: {
  note: NoteSummaryPublic
  actions: NoteCardActions
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-xs"
          // Always visible on touch, where there is no hover to reveal it.
          className="shrink-0 opacity-100 md:opacity-0 md:group-hover/note:opacity-100 md:group-focus-within/note:opacity-100"
          aria-label={`Actions for ${note.title || "Untitled"}`}
          data-testid="notes-card-menu"
        >
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {!note.archived && (
          <DropdownMenuItem
            onClick={() => actions.onPin(note)}
            data-testid="notes-action-pin"
          >
            {note.pinned ? <PinOff /> : <Pin />}
            {note.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
        )}
        {!note.archived && (
          <DropdownMenuItem
            onClick={() => actions.onRemind(note)}
            data-testid="notes-action-remind"
          >
            <Bell />
            Remind me
          </DropdownMenuItem>
        )}
        <DropdownMenuItem
          onClick={() => actions.onClone(note)}
          data-testid="notes-action-clone"
        >
          <Copy />
          Make a copy
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => actions.onArchive(note)}
          data-testid={
            note.archived ? "notes-action-restore" : "notes-action-archive"
          }
        >
          {note.archived ? <ArchiveRestore /> : <Archive />}
          {note.archived ? "Restore" : "Archive"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onClick={() => actions.onDelete(note)}
          data-testid="notes-action-delete"
        >
          <Trash2 />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
