import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { UserNotesService } from "@/client"
import { ConflictBanner } from "@/components/Documents/ConflictBanner"
import { SaveIndicator } from "@/components/Documents/SaveIndicator"
import { Editor } from "@/components/Editor/Editor"
import { useDocumentEditor } from "@/components/Editor/useDocumentEditor"
import { PageContainer } from "@/components/Layout/PageContainer"
import { DictateButton } from "@/components/Notes/DictateButton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAutosave } from "@/hooks/useAutosave"
import { noteQuery } from "@/queries/userNotes"

export const Route = createFileRoute("/_layout/notes/$noteId")({
  component: NotePage,
  loader: ({ context: { queryClient }, params }) =>
    queryClient.ensureQueryData(noteQuery(params.noteId)),
  head: () => ({ meta: [{ title: "Note - PlusGPT" }] }),
  pendingComponent: () => (
    <PageContainer className="flex flex-col gap-4">
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-64 w-full" />
    </PageContainer>
  ),
})

interface SavePayload {
  title: string
  content: string
  content_format: "html"
  expected_version: number
}

function NotePage() {
  const { noteId } = Route.useParams()
  const { data: note, refetch } = useQuery(noteQuery(noteId))

  const [title, setTitle] = useState(note?.title ?? "")
  // `getPayload` runs at flush time, so it has to read refs rather than state.
  const titleRef = useRef(title)
  const htmlRef = useRef(note?.content_html ?? "")
  const autosaveRef = useRef<ReturnType<
    typeof useAutosave<SavePayload>
  > | null>(null)

  const setTitleBoth = (value: string) => {
    titleRef.current = value
    setTitle(value)
    autosaveRef.current?.markDirty()
  }

  const archived = note?.archived === true

  const editor = useDocumentEditor({
    content: note?.content_html ?? "",
    editable: !archived,
    variant: "note",
    className: "min-h-[40vh]",
    placeholder: "Write something down",
    onUpdate: (html) => {
      htmlRef.current = html
      autosaveRef.current?.markDirty()
    },
  })

  const autosave = useAutosave<SavePayload>({
    baseVersion: note?.version ?? 1,
    enabled: !archived,
    getPayload: () => ({
      title: titleRef.current,
      content: htmlRef.current,
      content_format: "html",
      expected_version: autosaveRef.current?.version ?? note?.version ?? 1,
    }),
    save: async (payload) => {
      const saved = (
        await UserNotesService.notesUpdateNote({
          path: { note_id: noteId },
          body: payload,
        })
      ).data
      return { version: saved.version }
    },
    onReload: async () => {
      const fresh = await refetch()
      const latest = fresh.data
      if (!latest) return
      titleRef.current = latest.title
      setTitle(latest.title)
      htmlRef.current = latest.content_html
      editor?.commands.setContent(latest.content_html, { emitUpdate: false })
    },
  })
  autosaveRef.current = autosave

  useEffect(() => {
    if (!note) return
    titleRef.current = note.title
    setTitle(note.title)
    htmlRef.current = note.content_html
  }, [note])

  if (!note) return null

  return (
    <PageContainer className="flex flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          size="icon-sm"
          asChild
          aria-label="Back to notes"
        >
          <Link to="/notes">
            <ArrowLeft />
          </Link>
        </Button>
        <Input
          value={title}
          onChange={(e) => setTitleBoth(e.target.value)}
          placeholder="Untitled"
          aria-label="Title"
          disabled={archived}
          className="h-9 min-w-0 flex-1 border-0 px-0 font-semibold text-lg shadow-none focus-visible:ring-0"
          data-testid="notes-title"
        />
        {!archived && (
          <DictateButton
            onText={(text) =>
              // At the caret, not at the end: dictation here is a way of
              // continuing where you already are.
              editor?.chain().focus().insertContent(text).run()
            }
          />
        )}
        <SaveIndicator
          status={autosave.status}
          lastSavedAt={autosave.lastSavedAt}
          error={autosave.error}
          onRetry={() => void autosave.retry()}
        />
      </div>

      {archived && (
        <p className="rounded-md border border-dashed px-3 py-2 text-muted-foreground text-sm">
          This note is archived, so it is read-only. Restore it to write in it
          again. It stays searchable either way.
        </p>
      )}

      {autosave.conflict && (
        <ConflictBanner
          conflict={autosave.conflict}
          onReload={() => void autosave.resolveConflict("reload")}
          onOverwrite={() => void autosave.resolveConflict("overwrite")}
        />
      )}

      <div data-testid="notes-editor">
        <Editor editor={editor} />
      </div>
    </PageContainer>
  )
}
