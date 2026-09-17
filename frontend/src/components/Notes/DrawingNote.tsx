import { useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { type NotePublic, UserNotesService } from "@/client"
import {
  DrawingSurface,
  type Stroke,
  toPng,
} from "@/components/Notes/DrawingSurface"
import { LoadingButton } from "@/components/ui/loading-button"
import { useUploadNoteAsset } from "@/queries/noteAssets"

/** The strokes on a note, or an empty sketch if it has never been drawn on. */
export function strokesOf(note: NotePublic): Stroke[] {
  const json = note.content_json as { strokes?: unknown } | null | undefined
  const strokes = json?.strokes
  return Array.isArray(strokes) ? (strokes as Stroke[]) : []
}

/**
 * A drawing note: the surface, and one Save.
 *
 * Not autosaved, and that is the whole decision. Every save of a drawing
 * rasterises it, uploads the picture and sends it to a vision model so the
 * sketch is findable by what is in it. Doing that on a debounce would run a
 * vision pass every few seconds while somebody is still drawing. One button,
 * one version, one description.
 */
export function DrawingNote({
  note,
  title,
  titleDirty = false,
  onSaved,
}: {
  note: NotePublic
  /** The title as it is being typed. A drawing saves it with the strokes. */
  title: string
  titleDirty?: boolean
  onSaved?: () => void
}) {
  const [strokes, setStrokes] = useState<Stroke[]>(() => strokesOf(note))
  const [dirty, setDirty] = useState(false)
  const upload = useUploadNoteAsset(note.id)

  const save = useMutation({
    mutationFn: async () => {
      // The strokes first: they are the drawing, and the picture is derived
      // from them. If the upload fails after this, the sketch is still safe.
      const saved = (
        await UserNotesService.notesUpdateNote({
          path: { note_id: note.id },
          body: {
            title,
            content_json: { caption: title, strokes },
            expected_version: note.version,
          },
        })
      ).data
      if (strokes.length > 0) await upload.mutateAsync(await toPng(strokes))
      return saved
    },
    onSuccess: () => {
      setDirty(false)
      toast.success("Drawing saved")
      onSaved?.()
    },
    onError: (error: Error) =>
      toast.error(error.message || "The drawing could not be saved"),
  })

  const readOnly = note.archived
  const unsaved = dirty || titleDirty

  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="notes-drawing">
      <DrawingSurface
        strokes={strokes}
        readOnly={readOnly}
        onChange={(next) => {
          setStrokes(next)
          setDirty(true)
        }}
      />
      {!readOnly && (
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 text-muted-foreground text-sm">
            {unsaved
              ? "Not saved yet."
              : "Saved. What you drew is read once so the sketch turns up in search."}
          </p>
          <LoadingButton
            loading={save.isPending}
            disabled={!unsaved}
            onClick={() => save.mutate()}
            data-testid="notes-drawing-save"
          >
            Save drawing
          </LoadingButton>
        </div>
      )}
    </div>
  )
}
